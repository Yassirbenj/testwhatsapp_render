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
from googleapiclient.http import MediaIoBaseUpload
import io
from llm import evaluate_cv_with_openai

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
try:
    print("Tentative de connexion à Google Sheets...")
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
    client = gspread.authorize(creds)
    sheet = client.open("leads whatsapp").sheet1  # Mets ici le nom exact de ton Google Sheet
    print("✅ Connexion à Google Sheets réussie")
except Exception as e:
    print(f"❌ Erreur lors de la connexion à Google Sheets: {str(e)}")
    raise

# Google Calendar Setup
SCOPES = ['https://www.googleapis.com/auth/calendar', 'https://www.googleapis.com/auth/drive']
creds = service_account.Credentials.from_service_account_file(CREDENTIALS_FILE_CALENDAR, scopes=SCOPES)
calendar_service = build('calendar', 'v3', credentials=creds)
drive_service = build('drive', 'v3', credentials=creds)

CALENDAR_ID = 'benjilaliyassir@gmail.com'
TIMEZONE = 'Africa/Casablanca'
print(calendar_service.calendarList().list().execute())
print(drive_service.files().list().execute())
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
with open('process_rdv.json', 'r') as f:
    process_rdv = json.load(f)

with open('process.json', 'r') as f:
    process_formation = json.load(f)

with open('process_recrutement.json', 'r') as f:
    process_recrutement = json.load(f)

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
                        sender = message['from']
                        if 'text' in message:
                            text = message['text'].get('body')
                        else:
                            send_message(sender,"Merci de répondre avec un message texte")
                            return "OK", 200

                        # Nettoyer les anciennes conversations
                        cleanup_old_conversations()

                        # Gérer la commande de réinitialisation
                        if text.lower() in ['reset', 'recommencer', 'nouveau', 'start']:
                            if sender in user_data:
                                del user_data[sender]
                            # Utiliser le premier message du process_rdv
                            send_step_message(sender, 0, process_rdv)
                            return "OK", 200

                        if sender not in user_data:
                            # Premier message - choisir le processus
                            user_data[sender] = {
                                'state': 'initial',
                                'current_step': 0,
                                'data': {},
                                'process': process_rdv,
                                'last_activity': datetime.now()
                            }
                            send_step_message(sender, 0, process_rdv)

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
                                    print(f"Utilisateur {sender} a terminé le process principal (no_reply). Passage à la prise de RDV.")
                                    send_message(sender, "À partir de quelle date souhaitez-vous prendre rendez-vous ? (ex: 2024-06-01)")
                                    user_data[sender]['state'] = 'ask_start_date'
                                    return "OK", 200

                                send_step_message(sender, user_data[sender]['current_step'], current_process)
                                return "OK", 200

                            if current_step['expected_answers'] != "free_text":
                                # Utiliser les réponses attendues stockées si disponibles
                                valid_answers = user_data[sender].get('current_expected_answers', current_step['expected_answers'])
                                if text not in valid_answers:
                                    send_message(sender, "Merci de répondre avec une option valide.")
                                    return "OK", 200

                            # Aller à la prochaine étape
                            next_step = current_step['next_step']
                            if isinstance(next_step, dict):
                                user_data[sender]['current_step'] = next_step.get(text, 99)
                            else:
                                user_data[sender]['current_step'] = next_step

                            # Vérifier si on a atteint la fin du processus
                            if user_data[sender]['current_step'] >= len(current_process):
                                print(f"Utilisateur {sender} a terminé le process principal. Passage à la prise de RDV.")
                                send_message(sender, "À partir de quelle date souhaitez-vous prendre rendez-vous ? (ex: 2024-06-01)")
                                user_data[sender]['state'] = 'ask_start_date'
                                return "OK", 200

                            send_step_message(sender, user_data[sender]['current_step'], current_process)
                            return "OK", 200

                        elif step_index >= len(current_process):
                            # Ici c'est fini, on lance la suite spéciale selon le processus
                            if state == 'initial':
                                print(f"Utilisateur {sender} a terminé le process principal. Passage à la suite.")

                                if current_process == process_rdv:
                                    # Proposer une date pour prise de rendez-vous
                                    send_message(sender, "Merci pour vos réponses 🙏. Maintenant, choisissons ensemble un créneau pour votre rendez-vous.")
                                    send_message(sender, "À partir de quelle date souhaitez-vous prendre rendez-vous ? (ex: 2024-06-01)")
                                    user_data[sender]['state'] = 'ask_start_date'


                            if state == 'ask_start_date':
                                # Récupérer la date envoyée par l'utilisateur
                                try:
                                    start_date = datetime.strptime(text, "%Y-%m-%d")
                                except Exception:
                                    send_message(sender, "Merci d'indiquer une date au format AAAA-MM-JJ (ex: 2024-06-01)")
                                    return "OK", 200

                                slots = find_available_slots(start_date)
                                if not slots:
                                    send_message(sender, "Désolé, aucun créneau n'est disponible à partir de cette date. Merci d'en proposer une autre.")
                                    return "OK", 200

                                # Proposer les créneaux à l'utilisateur
                                msg = "Voici les créneaux disponibles :\n"
                                for idx, (slot_start, slot_end) in enumerate(slots, 1):
                                    msg += f"{idx}. {format_date_fr(slot_start)} - {format_date_fr(slot_end)}\n"
                                msg += "\nMerci de répondre par le numéro du créneau choisi."
                                send_message(sender, msg)

                                # Stocker les créneaux proposés pour ce user
                                user_data[sender]['available_slots'] = slots
                                user_data[sender]['state'] = 'choose_slot'
                                return "OK", 200

                            if state == 'choose_slot':
                                slots = user_data[sender].get('available_slots', [])
                                try:
                                    idx = int(text.strip()) - 1
                                    slot_start, slot_end = slots[idx]
                                except Exception:
                                    send_message(sender, "Merci de répondre par le numéro du créneau choisi.")
                                    return "OK", 200

                                # Créer le rendez-vous
                                link = create_appointment(sender, slot_start, slot_end)
                                send_message(sender, f"Votre rendez-vous est confirmé ! 📅\nLien Google Calendar : {link}")
                                user_data[sender]['state'] = 'completed'

                                # Construction de la ligne à enregistrer
                                record = [sender]  # Numéro de téléphone WhatsApp
                                for key, value in user_data[sender]['data'].items():
                                    record.append(value)
                                print("Données à enregistrer pour le recrutement :", user_data[sender]['data'])
                                # Ajouter une ligne dans Google Sheets
                                try:
                                    print(f"Tentative d'ajout dans Google Sheets: {record}")
                                    sheet.append_row(record)
                                    print(f"✅ Lead ajouté dans Google Sheet : {record}")
                                except Exception as e:
                                    print(f"❌ Erreur lors de l'ajout dans Google Sheets: {str(e)}")



        return "OK", 200

# === ENVOI DE MESSAGES WHATSAPP ===

def load_services():
    """Charge les services depuis le fichier services.json"""
    try:
        with open('services.json', 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Erreur lors du chargement des services: {str(e)}")
        return {"services": []}

def format_services_list(services):
    """Formate la liste des services pour l'affichage"""
    formatted_list = []
    for service in services['services']:
        formatted_list.append(f"{service['id']}️⃣ {service['name']} ({service['duration']} min)")
    return "\n".join(formatted_list)

def get_services_ids(services):
    """Récupère la liste des IDs des services"""
    return [service['id'] for service in services['services']]

def send_step_message(to_number, step_index, process):
    """Envoie le message de l'étape en cours avec les données dynamiques si nécessaire"""
    step = process[step_index]
    message = step['message']
    expected_answers = step['expected_answers']

    # Gérer les données dynamiques si présentes
    if 'dynamic_data' in step:
        if 'services_file' in step['dynamic_data']:
            services = load_services()
            # Remplacer les placeholders dans le message
            message = message.replace('{{services_list}}', format_services_list(services))
            # Remplacer les placeholders dans les réponses attendues
            if expected_answers == '{{services_ids}}':
                expected_answers = get_services_ids(services)
                # Stocker les réponses attendues dans user_data pour la validation
                if to_number in user_data:
                    user_data[to_number]['current_expected_answers'] = expected_answers

    send_message(to_number, message)
    return expected_answers

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
