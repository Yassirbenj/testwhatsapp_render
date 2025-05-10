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
def find_available_slots(start_date, service_duration, num_days=5):
    # En mode test, retourner des créneaux fictifs
    if os.getenv('TEST_MODE') == 'True':
        timezone = pytz.timezone(TIMEZONE)
        slots = []
        current_date = start_date

        # Convertir la durée en heures (arrondi au supérieur)
        duration_hours = (service_duration + 59) // 60
        print(f"\n[Info] Durée du service: {service_duration} minutes")

        # Créer 3 créneaux fictifs avec la bonne durée
        for i in range(3):
            slot_start = timezone.localize(datetime.combine(current_date, time(9 + i, 0)))
            slot_end = slot_start + timedelta(hours=duration_hours)
            slots.append((slot_start, slot_end))

        return slots

    # Code original pour le mode production
    timezone = pytz.timezone(TIMEZONE)
    slots = []

    # Convertir la durée en heures (arrondi au supérieur)
    duration_hours = (service_duration + 59) // 60

    # Ajuster les heures possibles en fonction de la durée
    possible_hours = []
    for hour in [9, 10, 11, 14, 15, 16, 17]:
        # Vérifier si le créneau complet tient dans la journée
        if hour + duration_hours <= 18:  # On s'arrête à 18h
            possible_hours.append(hour)

    current_date = start_date
    end_date = start_date + timedelta(days=num_days)

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
            local_end = local_start + timedelta(hours=duration_hours)

            start_utc = local_start.astimezone(pytz.utc).isoformat()
            end_utc = local_end.astimezone(pytz.utc).isoformat()

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
def create_appointment(sender, slot_start, slot_end, service_name, service_duration):
    # En mode test, simuler la création d'un rendez-vous
    if os.getenv('TEST_MODE') == 'True':
        print(f"\n[Création de rendez-vous simulée]")
        print(f"Date: {format_date_fr(slot_start)}")
        print(f"Durée: {service_duration} minutes")
        print(f"Service: {service_name}")
        print(f"Client: {user_data[sender]['data'].get('Nom complet', 'Client')}")
        return "https://calendar.google.com/mock-link"

    # Code original pour le mode production
    user_info = user_data[sender]['data']
    client_name = user_info.get('Nom complet') or user_info.get('Nom') or 'Client'
    modele = user_info.get('Modèle véhicule', '')
    annee = user_info.get('Année véhicule', '')

    description = f"""🧾 Détails du rendez-vous :
- Service : {service_name} ({service_duration} minutes)
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

                        # Gérer les réponses de boutons
                        if 'interactive' in message:
                            # Si c'est une réponse de bouton, récupérer l'ID du bouton
                            text = message['interactive']['button_reply']['id']
                        elif 'text' in message:
                            text = message['text'].get('body')
                        else:
                            send_message(sender, "Merci de répondre avec un message texte")
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

                        # pour debug
                        print(f"État: {state}, step index: {step_index}, longueur du processus: {len(current_process)}")

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
                                    send_date_buttons(sender)
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

                            # pour debug
                            print(f"next step is : {user_data[sender]['current_step']}")

                            # Vérifier si on a atteint la fin du processus
                            if user_data[sender]['current_step'] >= len(current_process):
                                print(f"Utilisateur {sender} a terminé le process principal. Passage à la prise de RDV.")
                                send_message(sender, "Merci pour vos réponses 🙏. Maintenant, choisissons ensemble un créneau pour votre rendez-vous.")
                                send_date_buttons(sender)  # Envoyer les boutons de date
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
                                    user_data[sender]['state'] = 'ask_start_date'

                            if state == 'ask_start_date':
                                # La date peut venir soit des boutons, soit d'une saisie manuelle
                                try:
                                    # Si c'est une réponse de bouton, le format est dd/MM/yyyy
                                    if text in [datetime.now().strftime("%d/%m/%Y"),
                                              (datetime.now() + timedelta(days=1)).strftime("%d/%m/%Y"),
                                              (datetime.now() + timedelta(days=2)).strftime("%d/%m/%Y")]:
                                        # Convertir le format dd/MM/yyyy en YYYY-MM-DD
                                        start_date = datetime.strptime(text, "%d/%m/%Y")
                                    else:
                                        # Sinon, essayer de parser la date saisie manuellement
                                        start_date = datetime.strptime(text, "%Y-%m-%d")
                                except Exception:
                                    send_message(sender, "Merci d'indiquer une date future au format JJ/MM/AAA (ex: 10/06/2025)")
                                    send_date_buttons(sender)  # Renvoyer les boutons
                                    return "OK", 200

                                service_id = user_data[sender]['data'].get('Service souhaité')
                                service_duration = None
                                service_name = None

                                # Charger les informations du service
                                with open('services.json', 'r') as f:
                                    services = json.load(f)
                                    for service in services['services']:
                                        if service['id'] == service_id:
                                            service_duration = int(service['duration'])
                                            service_name = service['name']
                                            break

                                # Vérifier que nous avons bien trouvé le service
                                if service_duration is None or service_name is None:
                                    print(f"Service non trouvé pour l'ID: {service_id}")
                                    send_message(sender, "Désolé, une erreur est survenue. Veuillez réessayer.")
                                    return "OK", 200

                                slots = find_available_slots(start_date, service_duration)
                                if not slots:
                                    send_message(sender, "Désolé, aucun créneau n'est disponible à partir de cette date. Merci d'en proposer une autre.")
                                    send_date_buttons(sender)  # Renvoyer les boutons
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

                                # Récupérer les informations du service
                                service_id = user_data[sender]['data'].get('Service souhaité')
                                with open('services.json', 'r') as f:
                                    services = json.load(f)
                                    for service in services['services']:
                                        if service['id'] == service_id:
                                            # Stocker les informations du service dans user_data
                                            user_data[sender]['service_info'] = {
                                                'name': service['name'],
                                                'duration': int(service['duration'])
                                            }
                                            break

                                # Vérifier que nous avons bien trouvé le service
                                if user_data[sender]['service_info'] is None:
                                    print(f"Service non trouvé pour l'ID: {service_id}")
                                    send_message(sender, "Désolé, une erreur est survenue. Veuillez réessayer.")
                                    return "OK", 200

                                # Créer le rendez-vous
                                service_info = user_data[sender].get('service_info', {})
                                link = create_appointment(
                                    sender,
                                    slot_start,
                                    slot_end,
                                    service_info.get('name'),
                                    service_info.get('duration')
                                )
                                send_message(sender, f"Votre rendez-vous est confirmé ! 📅\nLien Google Calendar : {link}")
                                user_data[sender]['state'] = 'completed'

                                # Stocker les informations du rendez-vous dans user_data
                                user_data[sender]['data'].update({
                                    'Date RDV': format_date_fr(slot_start),
                                    'Heure fin RDV': format_date_fr(slot_end),
                                    'Service': service_info.get('name'),
                                    'Durée service': f"{service_info.get('duration')} min"
                                })

                                # Construction de la ligne à enregistrer
                                record = [sender]  # Numéro de téléphone WhatsApp
                                for key, value in user_data[sender]['data'].items():
                                    record.append(value)

                                print("Données à enregistrer dans Google Sheet :", record)
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
    print(f"\n[Message envoyé]: {message}")
    # Si c'est un message de créneaux, afficher la durée
    if "Voici les créneaux disponibles" in message:
        service_id = user_data.get('test_user', {}).get('data', {}).get('Service souhaité')
        try:
            with open('services.json', 'r') as f:
                services = json.load(f)
                for service in services['services']:
                    if service['id'] == service_id:
                        print(f"\n[Info] Durée du service '{service['name']}': {service['duration']} minutes")
                        break
        except Exception as e:
            print(f"Erreur lors du chargement des services: {e}")

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

def send_date_buttons(sender):
    """Envoie les boutons de sélection de date"""
    url = f"https://graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    # Calculer les dates pour les 7 prochains jours
    today = datetime.now()
    dates = []
    for i in range(7):
        date = today + timedelta(days=i)
        dates.append(date.strftime("%Y-%m-%d"))

    # Créer les boutons
    buttons = []
    for date in dates[:3]:  # Limite à 3 boutons
        formatted_date = datetime.strptime(date, "%Y-%m-%d").strftime("%d/%m/%Y")
        buttons.append({
            "type": "reply",
            "reply": {
                "id": date,
                "title": formatted_date
            }
        })

    payload = {
        "messaging_product": "whatsapp",
        "to": sender,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {
                "text": "Choisissez une date pour votre rendez-vous :"
            },
            "action": {
                "buttons": buttons
            }
        }
    }

    print("Envoi des boutons de date:", payload)  # Debug
    response = requests.post(url, headers=headers, data=json.dumps(payload))
    print("Réponse envoi boutons:", response.status_code, response.json())

def test_process_local():
    """Test local du processus de rendez-vous en ligne de commande"""
    print("=== Test du processus de rendez-vous ===")

    # Simuler un utilisateur
    test_user = "test_user"

    # Initialiser l'utilisateur
    user_data[test_user] = {
        'state': 'initial',
        'current_step': 0,
        'data': {},
        'process': process_rdv,
        'last_activity': datetime.now()
    }

    # Simuler les messages
    test_messages = [
        "1",  # Prendre rendez-vous
        "John Doe",  # Nom
        "1",  # Service (Révision)
        "Renault Clio 2019",  # Véhicule
        "Ok",
        "10 juin 2025",
        "2025-05-09",  # Date (format YYYY-MM-DD comme dans les boutons)
        "1"  # Créneau
    ]

    # Simuler la conversation
    for message in test_messages:
        print("\n=== Nouveau message ===")
        print(f"Message reçu: {message}")

        # Simuler une requête WhatsApp
        test_request = {
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [{
                            "from": test_user,
                            "text": {"body": message}
                        }]
                    }
                }]
            }]
        }

        # Appeler le webhook avec la requête simulée
        with app.test_client() as client:
            response = client.post('/webhook', json=test_request)
            print(f"État actuel: {user_data[test_user]['state']}")
            print(f"Étape actuelle: {user_data[test_user]['current_step']}")
            print(f"Données collectées: {user_data[test_user]['data']}")
            print("---")

# === RUN APP ===
if __name__ == '__main__':
    # Mode test
    if os.getenv('TEST_MODE') == 'True':
        # Désactiver les dépendances externes pour le test
        import types

        # Créer des mock objects pour les services
        class MockSheet:
            def append_row(self, row):
                pass  # Ne rien afficher

        class MockService:
            def __init__(self, name):
                self.name = name

            def __getattr__(self, name):
                return lambda *args, **kwargs: None  # Ne rien afficher

        # Remplacer les services réels par des mocks
        sheet = MockSheet()
        calendar_service = MockService("Calendar")
        drive_service = MockService("Drive")

        # Modifier la fonction send_message pour le test
        def send_message(to_number, message):
            print(f"\n[Message envoyé]: {message}")

        # Modifier la fonction send_date_buttons pour le test
        def send_date_buttons(sender):
            print(f"\n[Options de date disponibles]")
            today = datetime.now()
            for i in range(3):
                date = today + timedelta(days=i)
                print(f"- {date.strftime('%d/%m/%Y')}")

        # Lancer le test
        test_process_local()
    else:
        app.run(port=5000)
