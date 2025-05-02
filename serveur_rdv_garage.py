'''solution de bot rdv'''

from flask import Flask, request, jsonify
import requests
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from googleapiclient.discovery import build
from google.oauth2 import service_account
from datetime import datetime, timedelta, time
import pytz
import os


# Dictionnaires pour la traduction des jours et mois en français
JOURS = {
    'Monday': 'Lundi',
    'Tuesday': 'Mardi',
    'Wednesday': 'Mercredi',
    'Thursday': 'Jeudi',
    'Friday': 'Vendredi',
    'Saturday': 'Samedi',
    'Sunday': 'Dimanche'
}

MOIS = {
    'January': 'Janvier',
    'February': 'Février',
    'March': 'Mars',
    'April': 'Avril',
    'May': 'Mai',
    'June': 'Juin',
    'July': 'Juillet',
    'August': 'Août',
    'September': 'Septembre',
    'October': 'Octobre',
    'November': 'Novembre',
    'December': 'Décembre'
}

def format_date_fr(date):
    """Formate une date en français sans dépendre de la locale"""
    jour = JOURS[date.strftime('%A')]
    mois = MOIS[date.strftime('%B')]
    return f"{jour} {date.day} {mois} {date.strftime('%H:%M')}"

app = Flask(__name__)


# 👉 details de connexion :
ACCESS_TOKEN = os.getenv('ACCESS_TOKEN')
PHONE_NUMBER_ID = os.getenv('PHONE_NUMBER_ID')
VERIFY_TOKEN = os.getenv('VERIFY_TOKEN')
CREDENTIALS_FILE=os.getenv('CREDENTIALS_FILE')
CREDENTIALS_FILE_CALENDAR=os.getenv('CREDENTIALS_FILE_CALENDAR')

# connexion google sheet
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
client = gspread.authorize(creds)
sheet = client.open("leads whatsapp").sheet1  # Mets ici le nom exact de ton Google Sheet

# Google Calendar Setup
SCOPES = ['https://www.googleapis.com/auth/calendar']
creds = service_account.Credentials.from_service_account_file(CREDENTIALS_FILE_CALENDAR, scopes=SCOPES)
calendar_service = build('calendar', 'v3', credentials=creds)

CALENDAR_ID = 'benjilaliyassir@gmail.com'
TIMEZONE = 'Africa/Casablanca'
print(calendar_service.calendarList().list().execute())

# Fonction de recherche de créneaux
def find_available_slots(start_date, num_days=5):
    timezone = pytz.timezone(TIMEZONE)
    slots = []

    # Définir les heures d'ouverture
    possible_hours = [9, 10, 11, 14, 15, 16, 17]

    # Plage de recherche
    current_date = start_date
    end_date = start_date + timedelta(days=num_days)

    # Convertir en UTC pour Google Calendar
    time_min = timezone.localize(datetime.combine(current_date, time.min)).astimezone(pytz.utc)
    time_max = timezone.localize(datetime.combine(end_date, time.max)).astimezone(pytz.utc)

    body = {
        "timeMin": time_min.isoformat(),
        "timeMax": time_max.isoformat(),
        "items": [{"id": CALENDAR_ID}]
    }

    freebusy = calendar_service.freebusy().query(body=body).execute()
    busy_times = freebusy['calendars'][CALENDAR_ID]['busy']

    while current_date <= end_date:
        for hour in possible_hours:
            local_start = timezone.localize(datetime.combine(current_date, time(hour, 0)))
            local_end = local_start + timedelta(hours=1)

            start_utc = local_start.astimezone(pytz.utc).isoformat()
            end_utc = local_end.astimezone(pytz.utc).isoformat()

            # Comparaison stricte avec tous les événements occupés
            overlapping = any(
                (busy['start'] <= start_utc < busy['end']) or
                (busy['start'] < end_utc <= busy['end']) or
                (start_utc <= busy['start'] and end_utc >= busy['end'])
                for busy in busy_times
            )

            if not overlapping and local_start > datetime.now(timezone):
                slots.append((local_start, local_end))

        current_date += timedelta(days=1)

    return slots[:3]

# Fonction créer rendez-vous
def create_appointment(sender, slot_start, slot_end):
    user_info = user_data[sender]['data']

    client_name = user_info.get('Nom complet') or user_info.get('Nom') or 'Client'
    service = user_info.get('Service souhaité', 'Service non précisé')
    modele = user_info.get('Modèle véhicule', '')
    annee = user_info.get('Année véhicule', '')

    description = f"""🧾 Détails du rendez-vous :
- Service : {service}
- Véhicule : {modele} ({annee})
- Client WhatsApp : {sender}"""

    event = {
        'summary': f"RDV Garage avec {client_name}",
        'description': description,
        'start': {
            'dateTime': slot_start.isoformat(),
            'timeZone': TIMEZONE
        },
        'end': {
            'dateTime': slot_end.isoformat(),
            'timeZone': TIMEZONE
        }
    }

    created_event = calendar_service.events().insert(calendarId=CALENDAR_ID, body=event).execute()
    return created_event.get('htmlLink')

# Charger les scénarios depuis les fichiers process
with open('process_garage.json', 'r') as f:
    process_garage = json.load(f)

with open('process.json', 'r') as f:
    process_formation = json.load(f)

# Stocker l'état et les réponses de chaque utilisateur
user_data = {}

# Nettoyer les anciennes conversations (plus de 24h)
def cleanup_old_conversations():
    current_time = datetime.now()
    to_delete = []
    for sender, data in user_data.items():
        if 'last_activity' in data:
            if (current_time - data['last_activity']).total_seconds() > 86400:  # 24 heures
                to_delete.append(sender)
    for sender in to_delete:
        del user_data[sender]

# === FLASK SETUP ===
app = Flask(__name__)

@app.route('/process-editor', methods=['GET', 'POST'])
def process_editor():
    if request.method == 'POST':
        try:
            process_data = request.form.get('process_data')
            process_type = request.form.get('process_type')

            # Sauvegarder le processus dans le bon fichier
            filename = 'process_garage.json' if process_type == 'garage' else 'process.json'
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(json.loads(process_data), f, ensure_ascii=False, indent=2)

            return jsonify({"status": "success", "message": "Processus sauvegardé avec succès!"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)})

    # Charger les processus existants
    try:
        with open('process_garage.json', 'r', encoding='utf-8') as f:
            process_garage_data = json.dumps(json.load(f), ensure_ascii=False, indent=2)
    except:
        process_garage_data = "[]"

    try:
        with open('process.json', 'r', encoding='utf-8') as f:
            process_formation_data = json.dumps(json.load(f), ensure_ascii=False, indent=2)
    except:
        process_formation_data = "[]"

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Éditeur de Processus</title>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.2/codemirror.min.js"></script>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.2/mode/javascript/javascript.min.js"></script>
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.2/codemirror.min.css">
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.2/theme/monokai.min.css">
        <style>
            body {{
                font-family: Arial, sans-serif;
                margin: 0;
                padding: 20px;
                background-color: #f5f5f5;
            }}
            .container {{
                max-width: 1200px;
                margin: 0 auto;
            }}
            .editor-container {{
                margin-bottom: 20px;
                background: white;
                padding: 20px;
                border-radius: 8px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }}
            .CodeMirror {{
                height: 400px;
                border: 1px solid #ddd;
                border-radius: 4px;
            }}
            h1 {{
                color: #333;
                margin-bottom: 20px;
            }}
            h2 {{
                color: #444;
                margin-top: 30px;
            }}
            button {{
                background-color: #4CAF50;
                color: white;
                padding: 10px 20px;
                border: none;
                border-radius: 4px;
                cursor: pointer;
                font-size: 16px;
                margin-top: 10px;
            }}
            button:hover {{
                background-color: #45a049;
            }}
            .status {{
                margin-top: 10px;
                padding: 10px;
                border-radius: 4px;
                display: none;
            }}
            .success {{
                background-color: #dff0d8;
                color: #3c763d;
                border: 1px solid #d6e9c6;
            }}
            .error {{
                background-color: #f2dede;
                color: #a94442;
                border: 1px solid #ebccd1;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Éditeur de Processus WhatsApp</h1>

            <div class="editor-container">
                <h2>Processus Garage</h2>
                <textarea id="garageEditor">{process_garage_data}</textarea>
                <button onclick="saveProcess('garage')">Sauvegarder Processus Garage</button>
                <div id="garageStatus" class="status"></div>
            </div>

            <div class="editor-container">
                <h2>Processus Formation</h2>
                <textarea id="formationEditor">{process_formation_data}</textarea>
                <button onclick="saveProcess('formation')">Sauvegarder Processus Formation</button>
                <div id="formationStatus" class="status"></div>
            </div>
        </div>

        <script>
            // Initialiser les éditeurs CodeMirror
            var garageEditor = CodeMirror.fromTextArea(document.getElementById("garageEditor"), {{
                mode: "application/json",
                theme: "monokai",
                lineNumbers: true,
                autoCloseBrackets: true,
                matchBrackets: true,
                indentUnit: 2,
                tabSize: 2
            }});

            var formationEditor = CodeMirror.fromTextArea(document.getElementById("formationEditor"), {{
                mode: "application/json",
                theme: "monokai",
                lineNumbers: true,
                autoCloseBrackets: true,
                matchBrackets: true,
                indentUnit: 2,
                tabSize: 2
            }});

            function saveProcess(type) {{
                const editor = type === 'garage' ? garageEditor : formationEditor;
                const statusDiv = document.getElementById(type + 'Status');

                try {{
                    // Valider le JSON
                    const processData = editor.getValue();
                    JSON.parse(processData); // Vérifie si le JSON est valide

                    // Envoyer les données au serveur
                    fetch('/process-editor', {{
                        method: 'POST',
                        headers: {{
                            'Content-Type': 'application/x-www-form-urlencoded',
                        }},
                        body: `process_data=${{encodeURIComponent(processData)}}&process_type=${{type}}`
                    }})
                    .then(response => response.json())
                    .then(data => {{
                        statusDiv.style.display = 'block';
                        if (data.status === 'success') {{
                            statusDiv.className = 'status success';
                            statusDiv.textContent = data.message;
                        }} else {{
                            statusDiv.className = 'status error';
                            statusDiv.textContent = 'Erreur: ' + data.message;
                        }}
                        setTimeout(() => {{
                            statusDiv.style.display = 'none';
                        }}, 3000);
                    }})
                    .catch(error => {{
                        statusDiv.style.display = 'block';
                        statusDiv.className = 'status error';
                        statusDiv.textContent = 'Erreur: ' + error.message;
                        setTimeout(() => {{
                            statusDiv.style.display = 'none';
                        }}, 3000);
                    }});
                }} catch (e) {{
                    statusDiv.style.display = 'block';
                    statusDiv.className = 'status error';
                    statusDiv.textContent = 'Erreur de syntaxe JSON: ' + e.message;
                    setTimeout(() => {{
                        statusDiv.style.display = 'none';
                    }}, 3000);
                }}
            }}
        </script>
    </body>
    </html>
    """

@app.route('/privacy', methods=['GET'])
def privacy_policy():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Politique de Confidentialité</title>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {
                font-family: Arial, sans-serif;
                line-height: 1.6;
                max-width: 800px;
                margin: 0 auto;
                padding: 20px;
            }
            h1 {
                color: #333;
                text-align: center;
            }
            h2 {
                color: #444;
                margin-top: 30px;
            }
            p {
                color: #666;
            }
        </style>
    </head>
    <body>
        <h1>Politique de Confidentialité</h1>

        <h2>1. Collecte des Informations</h2>
        <p>Nous collectons les informations suivantes :</p>
        <ul>
            <li>Numéro de téléphone WhatsApp</li>
            <li>Nom et prénom</li>
            <li>Informations relatives à votre demande (service souhaité, modèle de véhicule, etc.)</li>
        </ul>

        <h2>2. Utilisation des Informations</h2>
        <p>Les informations collectées sont utilisées pour :</p>
        <ul>
            <li>Gérer vos rendez-vous</li>
            <li>Vous contacter concernant votre demande</li>
            <li>Améliorer nos services</li>
        </ul>

        <h2>3. Protection des Informations</h2>
        <p>Nous mettons en œuvre des mesures de sécurité pour protéger vos informations personnelles. Vos données sont stockées de manière sécurisée et ne sont accessibles qu'aux personnes autorisées.</p>

        <h2>4. Partage des Informations</h2>
        <p>Nous ne vendons, n'échangeons et ne transférons pas vos informations personnelles à des tiers. Cela ne comprend pas les tierces parties de confiance qui nous aident à exploiter notre site web ou à mener nos activités, tant que ces parties conviennent de garder ces informations confidentielles.</p>

        <h2>5. Cookies</h2>
        <p>Notre site n'utilise pas de cookies.</p>

        <h2>6. Consentement</h2>
        <p>En utilisant notre service, vous consentez à notre politique de confidentialité.</p>

        <h2>7. Modifications</h2>
        <p>Nous nous réservons le droit de modifier cette politique de confidentialité à tout moment. Les modifications prendront effet dès leur publication sur cette page.</p>

        <h2>8. Contact</h2>
        <p>Si vous avez des questions concernant cette politique de confidentialité, vous pouvez nous contacter via WhatsApp.</p>
    </body>
    </html>
    """

@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    if request.method == 'GET':
        if request.args.get("hub.mode") == "subscribe" and request.args.get("hub.verify_token") == VERIFY_TOKEN:
            return request.args.get("hub.challenge"), 200
        return "Erreur de vérification", 403

    if request.method == 'POST':
        data = request.get_json()

        if data.get('entry'):
            for entry in data['entry']:
                for change in entry['changes']:
                    value = change.get('value')
                    messages = value.get('messages')
                    if messages:
                        message = messages[0]
                        text = message.get('text', {}).get('body')
                        sender = message['from']

                        # Nettoyer les anciennes conversations
                        cleanup_old_conversations()

                        # Gérer la commande de réinitialisation
                        if text.lower() in ['reset', 'recommencer', 'nouveau', 'start']:
                            if sender in user_data:
                                del user_data[sender]
                            send_message(sender, "Bienvenue ! Que souhaitez-vous faire ?\n1️⃣ Prendre rendez-vous au garage\n2️⃣ S'informer sur nos formations")
                            return "OK", 200

                        if sender not in user_data:
                            # Premier message - choisir le processus
                            if text.lower() == "1":
                                user_data[sender] = {
                                    'state': 'initial',
                                    'current_step': 0,
                                    'data': {},
                                    'process': process_garage,
                                    'last_activity': datetime.now()
                                }
                                send_step_message(sender, 0, process_garage)
                            elif text.lower() == "2":
                                user_data[sender] = {
                                    'state': 'initial',
                                    'current_step': 0,
                                    'data': {},
                                    'process': process_formation,
                                    'last_activity': datetime.now()
                                }
                                send_step_message(sender, 0, process_formation)
                            else:
                                # Message initial pour choisir le processus
                                send_message(sender, "Bienvenue ! Que souhaitez-vous faire ?\n1️⃣ Prendre rendez-vous au garage\n2️⃣ S'informer sur nos formations")
                            return "OK", 200

                        # Mettre à jour le timestamp de dernière activité
                        user_data[sender]['last_activity'] = datetime.now()

                        state = user_data[sender]['state']
                        step_index = user_data[sender]['current_step']
                        current_process = user_data[sender]['process']

                        if step_index < len(current_process):
                            current_step = current_process[step_index]

                            # === SAUVEGARDE de la réponse utilisateur ===
                            save_key = current_step.get('save_as')
                            if save_key:
                                user_data[sender]['data'][save_key] = text

                            if current_step['expected_answers'] == "no_reply":
                                # Pas besoin d'attendre l'utilisateur
                                next_step = current_step['next_step']
                                if isinstance(next_step, dict):
                                    user_data[sender]['current_step'] = next_step.get(text, 99)
                                else:
                                    user_data[sender]['current_step'] = next_step

                                # ⚡ Directement lancer la suite
                                if user_data[sender]['current_step'] >= len(current_process):
                                    if current_process == process_garage:
                                        print(f"Utilisateur {sender} a terminé le process principal (no_reply). Passage à la prise de RDV.")
                                        send_message(sender, "À partir de quelle date souhaitez-vous prendre rendez-vous ? (ex: 2024-06-01)")
                                        user_data[sender]['state'] = 'ask_start_date'
                                    else:
                                        # Logique spécifique pour le processus formation
                                        send_message(sender, "Merci pour vos réponses ! Nous vous contacterons bientôt.")
                                        user_data[sender]['state'] = 'completed'
                                else:
                                    send_step_message(sender, user_data[sender]['current_step'], current_process)

                                return "OK", 200

                            if current_step['expected_answers'] != "free_text":
                                if text not in current_step['expected_answers']:
                                    send_message(sender, "Merci de répondre avec une option valide.")
                                    return "OK", 200

                            # Aller à la prochaine étape
                            next_step = current_step['next_step']
                            if isinstance(next_step, dict):
                                user_data[sender]['current_step'] = next_step.get(text, 99)
                            else:
                                user_data[sender]['current_step'] = next_step

                            send_step_message(sender, user_data[sender]['current_step'], current_process)
                            return "OK", 200

                        elif step_index >= len(current_process):
                            # Ici c'est fini, on lance la suite spéciale selon le processus
                            if state == 'initial':
                                print(f"Utilisateur {sender} a terminé le process principal. Passage à la suite.")

                                if current_process == process_garage:
                                    # Proposer une date pour prise de rendez-vous
                                    send_message(sender, "Merci pour vos réponses 🙏. Maintenant, choisissons ensemble un créneau pour votre rendez-vous.")
                                    send_message(sender, "À partir de quelle date souhaitez-vous prendre rendez-vous ? (ex: 2024-06-01)")
                                    user_data[sender]['state'] = 'ask_start_date'

                                    # Construction de la ligne à enregistrer
                                    record = [sender]  # Numéro de téléphone WhatsApp
                                    for key, value in user_data[sender]['data'].items():
                                        record.append(value)

                                    # Ajouter une ligne dans Google Sheets
                                    sheet.append_row(record)
                                    print(f"✅ Lead ajouté dans Google Sheet : {record}")
                                else:
                                    # Logique pour le processus formation
                                    send_message(sender, "Merci pour vos réponses ! Nous vous contacterons bientôt.")
                                    user_data[sender]['state'] = 'completed'

                            # Le reste du code pour la gestion des rendez-vous reste inchangé
                            elif state == 'ask_start_date':
                                try:
                                    user_date = datetime.strptime(text, "%Y-%m-%d").date()
                                    slots = find_available_slots(user_date)

                                    if not slots:
                                        send_message(sender, "Désolé, aucun créneau disponible sur cette période. Merci d'indiquer une autre date.")
                                    else:
                                        user_data[sender]['slots'] = slots
                                        message = "Voici nos créneaux disponibles :\n"
                                        for idx, (start, _) in enumerate(slots, 1):
                                            message += f"{idx}️⃣ {format_date_fr(start)}\n"
                                        message += "\nMerci de répondre par 1, 2 ou 3 pour choisir votre créneau."
                                        send_message(sender, message)
                                        user_data[sender]['state'] = 'choose_slot'
                                except ValueError:
                                    send_message(sender, "Merci d'indiquer une date valide au format AAAA-MM-JJ.")

                            elif user_data[sender]['state'] == 'choose_slot':
                                if text in ["1", "2", "3"]:
                                    idx = int(text) - 1
                                    slots = user_data[sender]['slots']
                                    selected_start, selected_end = slots[idx]

                                    create_appointment(sender, selected_start, selected_end)

                                    send_message(sender, f"✅ Votre rendez-vous est confirmé pour le {format_date_fr(selected_start)} ! Merci et à bientôt 🚗")
                                    user_data[sender]['state'] = 'completed'

                                else:
                                    send_message(sender, "Merci de choisir 1, 2 ou 3.")

        return "OK", 200

# === ENVOI DE MESSAGES WHATSAPP ===

def send_step_message(to_number, step_index, process):
    message = process[step_index]['message']
    send_message(to_number, message)

def send_message(to_number, message):
    url = f"https://graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": {
            "body": message
        }
    }

    # Vérification des variables d'environnement
    if not ACCESS_TOKEN:
        print("ERROR: ACCESS_TOKEN is not set in environment variables")
        return
    if not PHONE_NUMBER_ID:
        print("ERROR: PHONE_NUMBER_ID is not set in environment variables")
        return

    print(f"Debug - Using PHONE_NUMBER_ID: {PHONE_NUMBER_ID}")
    print(f"Debug - ACCESS_TOKEN starts with: {ACCESS_TOKEN[:10]}...")

    response = requests.post(url, headers=headers, data=json.dumps(payload))
    print("Réponse envoi message:", response.status_code, response.json())

    if response.status_code == 400:
        error_data = response.json().get('error', {})
        print(f"Error details: {error_data.get('message')}")
        print(f"Error type: {error_data.get('type')}")
        print(f"Error code: {error_data.get('code')}")
        if 'error_data' in error_data:
            print(f"Additional error data: {error_data['error_data']}")

# === RUN APP ===
if __name__ == '__main__':
    app.run(port=5000)
