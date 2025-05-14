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

# Initialiser un cache pour les services calendar par garage
garage_calendar_services = {}

def get_garage_calendar_service(garage_id):
    """Obtient le service calendar pour un garage spécifique"""
    global garage_calendar_services

    # Si le service a déjà été initialisé, le retourner
    if garage_id in garage_calendar_services:
        return garage_calendar_services[garage_id]

    try:
        # Récupérer les informations du garage
        garages = load_garages()
        target_garage = None
        for garage in garages['garages']:
            if garage['id'] == garage_id:
                target_garage = garage
                break

        if not target_garage:
            print(f"[ERROR] Garage non trouvé pour l'ID: {garage_id}")
            return {'service': calendar_service, 'calendar_id': CALENDAR_ID}  # Retourner le service par défaut

        # Récupérer les credentials du .env ou des variables d'environnement
        env_credential_key = f"CREDENTIALS_FILE_CALENDAR_{garage_id.upper()}"
        credentials_path = os.getenv(env_credential_key, CREDENTIALS_FILE_CALENDAR)

        print(f"[DEBUG] Utilisation des credentials à partir de {env_credential_key}: {credentials_path}")

        # Récupérer le calendar_id
        calendar_id = target_garage.get('calendar_id', CALENDAR_ID)

        # Si les credentials existent
        if os.path.exists(credentials_path):
            # Initialiser le service avec les credentials spécifiques du garage
            credentials = service_account.Credentials.from_service_account_file(
                credentials_path, scopes=SCOPES
            )
            specific_service = build('calendar', 'v3', credentials=credentials)

            # Stocker dans le cache
            garage_calendar_services[garage_id] = {
                'service': specific_service,
                'calendar_id': calendar_id
            }

            print(f"[INFO] Service calendar initialisé pour le garage {garage_id} avec calendar_id {calendar_id}")
            return garage_calendar_services[garage_id]
        else:
            print(f"[WARNING] Credentials non trouvés pour le garage {garage_id} (path: {credentials_path})")
            # Créer une entrée dans le cache avec le service par défaut
            garage_calendar_services[garage_id] = {
                'service': calendar_service,
                'calendar_id': calendar_id
            }
            return garage_calendar_services[garage_id]

    except Exception as e:
        print(f"[ERROR] Erreur lors de l'initialisation du service calendar pour le garage {garage_id}: {str(e)}")
        # Retourner le service par défaut
        return {'service': calendar_service, 'calendar_id': CALENDAR_ID}

# Fonction de recherche de créneaux
def find_available_slots(start_date, service_duration, num_days=5, garage_id=None):
    print(f"\n[DEBUG] Recherche de créneaux disponibles:")
    print(f"- Date de début: {start_date}")
    print(f"- Durée du service: {service_duration} minutes")
    print(f"- Nombre de jours: {num_days}")
    print(f"- Garage ID: {garage_id}")

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

    # Code pour le mode production
    timezone = pytz.timezone(TIMEZONE)
    slots = []

    # Récupérer le service calendar et l'ID du calendrier pour ce garage
    if garage_id:
        calendar_info = get_garage_calendar_service(garage_id)
        specific_calendar_service = calendar_info['service']
        specific_calendar_id = calendar_info['calendar_id']

        # Récupérer les paramètres du garage
        garages = load_garages()
        closing_hour = 18  # Valeur par défaut
        working_hours = [9, 10, 11, 14, 15, 16, 17]  # Valeurs par défaut
        max_appointments_per_slot = 1  # Valeur par défaut

        for garage in garages['garages']:
            if garage['id'] == garage_id:
                closing_hour = garage.get('closing_hour', 18)  # Utiliser 18 si non spécifié
                working_hours = garage.get('working_hours', working_hours)  # Utiliser les heures par défaut si non spécifiées
                max_appointments_per_slot = int(garage.get('max_appointments_per_slot', 1))  # Utiliser 1 si non spécifié et convertir en int
                print(f"[DEBUG] Heure de fermeture pour {garage_id}: {closing_hour}h")
                print(f"[DEBUG] Heures de travail pour {garage_id}: {working_hours}")
                print(f"[DEBUG] Nombre max de RDV par créneau pour {garage_id}: {max_appointments_per_slot} (type: {type(max_appointments_per_slot)})")
                break
    else:
        specific_calendar_service = calendar_service
        specific_calendar_id = CALENDAR_ID
        closing_hour = 18  # Valeur par défaut si pas de garage spécifié
        working_hours = [9, 10, 11, 14, 15, 16, 17]  # Valeurs par défaut
        max_appointments_per_slot = 1  # Valeur par défaut

    # Vérifier d'abord si le calendrier existe
    try:
        calendar_info = specific_calendar_service.calendars().get(calendarId=specific_calendar_id).execute()
        print(f"[INFO] Calendrier trouvé: {calendar_info.get('summary', specific_calendar_id)}")
    except Exception as e:
        print(f"[WARNING] Calendrier non trouvé: {specific_calendar_id}. Erreur: {str(e)}")
        print(f"[INFO] Utilisation du calendrier par défaut: {CALENDAR_ID}")
        specific_calendar_service = calendar_service
        specific_calendar_id = CALENDAR_ID

    # Convertir la durée en heures (arrondi au supérieur)
    duration_hours = (service_duration + 59) // 60

    # Ajuster les heures possibles en fonction de la durée
    possible_hours = []
    for hour in working_hours:
        # Vérifier si le créneau complet tient dans la journée en fonction de l'heure de fermeture du garage
        if hour + duration_hours <= closing_hour:
            possible_hours.append(hour)

    print(f"[DEBUG] Heures possibles selon la durée et l'heure de fermeture: {possible_hours}")

    # Si aucune heure possible, utiliser des heures par défaut
    if not possible_hours:
        print("[WARNING] Aucune heure de travail possible avec la durée demandée. Utilisation d'heures standards.")
        possible_hours = [9, 10, 11]  # Heures standards du matin

    current_date = start_date
    end_date = start_date + timedelta(days=num_days)

    time_min = timezone.localize(datetime.combine(current_date, time.min)).astimezone(pytz.utc)
    time_max = timezone.localize(datetime.combine(end_date, time.max)).astimezone(pytz.utc)

    # Récupérer tous les événements dans l'intervalle de temps
    try:
        # Récupérer tous les événements dans l'intervalle
        events_result = specific_calendar_service.events().list(
            calendarId=specific_calendar_id,
            timeMin=time_min.isoformat(),
            timeMax=time_max.isoformat(),
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        events = events_result.get('items', [])

        # Obtenir aussi les plages horaires occupées
        freebusy_query = {
            "timeMin": time_min.isoformat(),
            "timeMax": time_max.isoformat(),
            "items": [{"id": specific_calendar_id}]
        }
        freebusy = specific_calendar_service.freebusy().query(body=freebusy_query).execute()
        busy_times = freebusy['calendars'][specific_calendar_id]['busy']

        # Créer un dictionnaire pour compter le nombre de rendez-vous par créneau horaire
        slot_counts = {}  # Clé: 'YYYY-MM-DD-HH', Valeur: nombre de rendez-vous

        # Compter les rendez-vous existants par créneau
        print(f"[DEBUG] Nombre total d'événements trouvés sur la période: {len(events)}")
        for event in events:
            if 'dateTime' in event['start']:
                event_start = datetime.fromisoformat(event['start']['dateTime'].replace('Z', '+00:00'))
                event_start_local = event_start.astimezone(timezone)
                # Créer une clé représentant le créneau horaire (jour-heure)
                slot_key = event_start_local.strftime('%Y-%m-%d-%H')

                # Incrémenter le compteur pour ce créneau
                if slot_key in slot_counts:
                    slot_counts[slot_key] += 1
                else:
                    slot_counts[slot_key] = 1
                print(f"[DEBUG] Événement trouvé: {event.get('summary', 'Sans titre')} - Début: {event_start_local.strftime('%Y-%m-%d %H:%M')} - Créneau: {slot_key}")

        print(f"[DEBUG] Nombre de rendez-vous par créneau: {slot_counts}")
        print(f"[DEBUG] Nombre maximum de rendez-vous par créneau autorisé: {max_appointments_per_slot}")

        # Parcourir les jours et les heures pour trouver des créneaux disponibles
        slots_checked = 0
        slots_available = 0
        slots_rejected_count = 0
        slots_rejected_overlap = 0

        while current_date < end_date:
            for hour in possible_hours:
                local_start = timezone.localize(datetime.combine(current_date, time(hour, 0)))
                local_end = local_start + timedelta(hours=duration_hours)

                # Créer la clé pour ce créneau
                slot_key = local_start.strftime('%Y-%m-%d-%H')
                slots_checked += 1

                # Obtenir le nombre actuel de rendez-vous pour ce créneau
                current_count = slot_counts.get(slot_key, 0)

                # Vérifier si le créneau est dans le futur
                if local_start > datetime.now(timezone):
                    # Vérifier explicitement la condition
                    is_below_max = current_count < max_appointments_per_slot

                    print(f"[DEBUG] Vérification du créneau {local_start.strftime('%Y-%m-%d %H:%M')}")
                    print(f"[DEBUG] Compteur actuel: {current_count}, Max autorisé: {max_appointments_per_slot}, Disponible: {is_below_max}")

                    # N'autoriser le créneau que si le nombre de rendez-vous est inférieur au maximum
                    if is_below_max:
                        # Vérifier aussi si le créneau n'est pas occupé (par des événements de type blocage)
                        start_utc = local_start.astimezone(pytz.utc).isoformat()
                        end_utc = local_end.astimezone(pytz.utc).isoformat()

                        overlapping = any(
                            (busy['start'] <= start_utc < busy['end']) or
                            (busy['start'] < end_utc <= busy['end']) or
                            (start_utc <= busy['start'] and end_utc >= busy['end'])
                            for busy in busy_times
                        )

                        if not overlapping:
                            slots.append((local_start, local_end))
                            slots_available += 1
                            print(f"[DEBUG] Créneau disponible trouvé: {local_start.strftime('%Y-%m-%d %H:%M')} - Compteur actuel: {current_count}/{max_appointments_per_slot}")
                        else:
                            slots_rejected_overlap += 1
                            print(f"[DEBUG] Créneau rejeté (chevauchement): {local_start.strftime('%Y-%m-%d %H:%M')} - Compteur: {current_count}/{max_appointments_per_slot}")
                    else:
                        slots_rejected_count += 1
                        print(f"[DEBUG] Créneau rejeté (complet): {local_start.strftime('%Y-%m-%d %H:%M')} - Compteur: {current_count}/{max_appointments_per_slot}")

            current_date += timedelta(days=1)

        print(f"[DEBUG] Résumé de la recherche:")
        print(f"- Créneaux vérifiés: {slots_checked}")
        print(f"- Créneaux disponibles trouvés: {slots_available}")
        print(f"- Créneaux rejetés (complets): {slots_rejected_count}")
        print(f"- Créneaux rejetés (chevauchements): {slots_rejected_overlap}")
        print(f"- Total créneaux retournés: {min(len(slots), 3)}")

        return slots[:3]  # Limiter à 3 créneaux

    except Exception as e:
        print(f"[ERROR] Erreur lors de la recherche d'événements: {str(e)}")
        # En cas d'erreur, retourner des créneaux disponibles à des heures standard
        print("[INFO] Génération de créneaux standard en raison de l'erreur de calendrier")

        # Utiliser les heures de travail du garage pour proposer des créneaux standards
        standard_hours = working_hours[:3] if len(working_hours) >= 3 else working_hours  # Prendre les 3 premières heures ou toutes si moins de 3

        for i in range(3):  # Proposer 3 jours à partir de la date demandée
            day = start_date + timedelta(days=i)
            for hour in standard_hours:
                if hour + duration_hours <= closing_hour:  # Vérifier que le service tient dans la journée selon l'heure de fermeture
                    slot_start = timezone.localize(datetime.combine(day, time(hour, 0)))
                    slot_end = slot_start + timedelta(hours=duration_hours)

                    # Ne pas proposer de créneaux dans le passé
                    if slot_start > datetime.now(timezone):
                        slots.append((slot_start, slot_end))

    # Limiter à 3 créneaux maximum
    return slots[:3]

# Fonction créer rendez-vous
def create_appointment(sender, slot_start, slot_end, service_name, service_duration):
    print(f"\n[DEBUG] Création d'un rendez-vous:")
    print(f"- Client: {sender}")
    print(f"- Début: {slot_start}")
    print(f"- Fin: {slot_end}")
    print(f"- Service: {service_name}")
    print(f"- Durée: {service_duration} minutes")

    # Récupérer l'ID du garage sélectionné
    garage_id = None
    if sender in user_data and 'selected_garage' in user_data[sender]:
        garage_id = user_data[sender]['selected_garage']['id']
        print(f"- Garage ID: {garage_id}")

    # En mode test, simuler la création d'un rendez-vous
    if os.getenv('TEST_MODE') == 'True':
        print(f"\n[Création de rendez-vous simulée]")
        print(f"Date: {format_date_fr(slot_start)}")
        print(f"Durée: {service_duration} minutes")
        print(f"Service: {service_name}")
        print(f"Client: {user_data[sender]['data'].get('Nom complet', 'Client')}")
        return "https://calendar.google.com/mock-link"

    # Code pour le mode production
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

    # Utiliser le service et le calendar_id spécifiques au garage
    if garage_id:
        calendar_info = get_garage_calendar_service(garage_id)
        specific_calendar_service = calendar_info['service']
        specific_calendar_id = calendar_info['calendar_id']
    else:
        specific_calendar_service = calendar_service
        specific_calendar_id = CALENDAR_ID

    created_event = specific_calendar_service.events().insert(calendarId=specific_calendar_id, body=event).execute()
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
    print("\n[DEBUG] Réception d'une requête webhook")
    if request.method == 'GET':
        print("[DEBUG] Méthode GET détectée")
        if request.args.get("hub.mode") == "subscribe" and request.args.get("hub.verify_token") == VERIFY_TOKEN:
            print("[DEBUG] Vérification du token réussie")
            return request.args.get("hub.challenge"), 200
        print("[DEBUG] Échec de la vérification du token")
        return "Erreur de vérification", 403

    if request.method == 'POST':
        print("[DEBUG] Méthode POST détectée")
        data = request.get_json()
        print(f"[DEBUG] Données reçues: {json.dumps(data, indent=2)}")

        if data.get('entry'):
            for entry in data['entry']:
                for change in entry['changes']:
                    value = change.get('value')
                    messages = value.get('messages')
                    if messages:
                        message = messages[0]
                        sender = message['from']
                        print(f"[DEBUG] Message reçu de {sender}")

                        # Gérer les réponses interactives
                        if 'interactive' in message:
                            print("[DEBUG] Message interactif détecté")
                            interactive = message['interactive']
                            # Gérer les réponses de boutons
                            if 'button_reply' in interactive:
                                text = interactive['button_reply']['id']
                                print(f"[DEBUG] Réponse bouton: {text}")
                            # Gérer les réponses de liste
                            elif 'list_reply' in interactive:
                                text = interactive['list_reply']['id']
                                print(f"[DEBUG] Réponse liste: {text}")
                            else:
                                print("[DEBUG] Type interactif non géré")
                                send_message(sender, "Merci de répondre avec un message texte")
                                return "OK", 200
                        elif 'text' in message:
                            text = message['text'].get('body')
                            print(f"[DEBUG] Message texte: {text}")
                        else:
                            print("[DEBUG] Type de message non géré")
                            send_message(sender, "Merci de répondre avec un message texte")
                            return "OK", 200

                        # Nettoyer les anciennes conversations
                        cleanup_old_conversations()

                        # Gérer la commande de réinitialisation
                        if text.lower() in ['reset', 'recommencer', 'nouveau', 'start']:
                            print("[DEBUG] Commande de réinitialisation détectée")
                            if sender in user_data:
                                del user_data[sender]
                            send_initial_garage_message(sender)
                            return "OK", 200

                        if sender not in user_data:
                            print("[DEBUG] Nouvel utilisateur détecté")
                            # Premier message - choisir le garage
                            user_data[sender] = {
                                'state': 'initial',
                                'current_step': 0,
                                'data': {},
                                'last_activity': datetime.now()
                            }
                            send_initial_garage_message(sender)
                            return "OK", 200

                        # Mettre à jour le timestamp de dernière activité
                        user_data[sender]['last_activity'] = datetime.now()

                        # Si l'utilisateur n'a pas encore sélectionné de garage
                        if 'selected_garage' not in user_data[sender]:
                            garage = handle_garage_selection(sender, text)
                            if garage:
                                user_data[sender]['selected_garage'] = garage
                            return "OK", 200

                        # Si l'utilisateur a répondu à la confirmation du garage
                        if 'selected_garage' in user_data[sender] and user_data[sender].get('state') == 'initial':
                            if text == 'confirm_garage':
                                # Initialiser le processus avec le process_id du garage
                                user_data[sender]['process'] = process_rdv  # Utiliser le processus par défaut
                                user_data[sender]['state'] = 'initial'
                                user_data[sender]['current_step'] = 0
                                # Envoyer le premier message du processus
                                send_step_message(sender, 0, process_rdv)
                                return "OK", 200
                            elif text == 'change_garage':
                                # Supprimer le garage sélectionné
                                del user_data[sender]['selected_garage']
                                # Renvoyer la liste des garages
                                send_garage_selection_message(sender)
                                return "OK", 200

                        # Continuer avec le processus normal si un garage est sélectionné
                        state = user_data[sender]['state']
                        step_index = user_data[sender]['current_step']
                        current_process = user_data[sender]['process']
                        next_step = current_process[step_index]['next_step']

                        print(f"[DEBUG] État actuel:")
                        print(f"- État: {state}")
                        print(f"- Index étape: {step_index}")
                        print(f"- Longueur processus: {len(current_process)}")
                        print(f"- Prochaine étape: {next_step}")

                        # Convertir next_step en int si c'est une chaîne de caractères
                        if isinstance(next_step, str) and next_step.isdigit():
                            next_step = int(next_step)
                            print(f"[DEBUG] next_step converti en int: {next_step}")

                        if isinstance(next_step, dict) or (isinstance(next_step, (int, str)) and int(next_step) < 99):
                            print("[DEBUG] Traitement d'une étape normale")
                            current_step = current_process[step_index]
                            print(f"[DEBUG] Étape actuelle: {current_step}")

                            # === SAUVEGARDE de la réponse utilisateur ===
                            save_key = current_step.get('save_as')
                            print(f"[DEBUG] Save key trouvé: {save_key}")
                            print(f"[DEBUG] Réponse utilisateur: {text}")

                            if save_key:
                                print(f"[DEBUG] Sauvegarde de la réponse sous la clé: {save_key}")
                                user_data[sender]['data'][save_key] = text

                                # Définir le type de processus en fonction de la réponse
                                if save_key == 'Type de demande':
                                    print(f"[DEBUG] Type de demande détecté")
                                    print(f"[DEBUG] Message reçu: '{text}'")
                                    if text == '1':
                                        user_data[sender]['process_type'] = 'creation'
                                        print(f"[DEBUG] Process type défini à: creation")
                                    elif text == '2':
                                        user_data[sender]['process_type'] = 'annulation'
                                        print(f"[DEBUG] Process type défini à: annulation")
                                    elif text == '3':
                                        user_data[sender]['process_type'] = 'autres'
                                        print(f"[DEBUG] Process type défini à: autres")
                                    else:
                                        print(f"[DEBUG] Type de demande non reconnu: {text}")

                            if current_step['expected_answers'] != "free_text":
                                print("[DEBUG] Vérification des réponses attendues")
                                # Utiliser les réponses attendues stockées si disponibles
                                valid_answers = user_data[sender].get('current_expected_answers', current_step['expected_answers'])
                                if text not in valid_answers:
                                    print(f"[DEBUG] Réponse invalide: {text}")
                                    send_message(sender, "Merci de répondre avec une option valide.")
                                    return "OK", 200

                            # Aller à la prochaine étape
                            next_step = current_step['next_step']
                            print(f"[DEBUG] Prochaine étape avant traitement: {next_step}")

                            if isinstance(next_step, dict):
                                print(f"[DEBUG] next_step est un dictionnaire: {next_step}")
                                user_data[sender]['current_step'] = next_step.get(text, 99)
                            else:
                                print(f"[DEBUG] next_step est une valeur simple: {next_step}")
                                user_data[sender]['current_step'] = next_step

                            print(f"[DEBUG] next step après traitement: {user_data[sender]['current_step']}")

                            send_step_message(sender, user_data[sender]['current_step'], current_process)
                            return "OK", 200
                        else:
                            print(f"[DEBUG] Fin du processus - next_step: {next_step}")
                            # Ici c'est fini, on lance la suite spéciale selon le processus
                            print(f"[DEBUG] Valeur de process_type: {user_data[sender].get('process_type')}")
                            if user_data[sender].get("process_type") == "creation":
                                print("[DEBUG] Lancement du processus de création")
                                return handle_creation_process(sender, state, text, message)
                            elif user_data[sender].get("process_type") == "annulation":
                                print("[DEBUG] Lancement du processus d'annulation")
                                return handle_cancellation_process(sender, state, text, message)
                            elif user_data[sender].get("process_type") == "autres":
                                print("[DEBUG] Lancement du processus d'autres")
                                return handle_other_process(sender, state)
                            print("[DEBUG] Aucun processus spécial trouvé")
                            return "OK", 200

                        print("[DEBUG] Fin du traitement du message")
                        return "OK", 200

        print("[DEBUG] Aucun message trouvé dans la requête")
        return "OK", 200

    print("[DEBUG] Méthode non supportée")
    return "Méthode non supportée", 405

# === ENVOI DE MESSAGES WHATSAPP ===

def load_services():
    """Charge les services depuis le fichier services.json"""
    try:
        with open('services.json', 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Erreur lors du chargement des services: {str(e)}")
        return {"services": []}

def get_garage_services(garage_id):
    """Récupère les services d'un garage spécifique depuis garages.json"""
    try:
        garages = load_garages()
        for garage in garages['garages']:
            if garage['id'] == garage_id:
                return {"services": garage['services']}
        # Si le garage n'est pas trouvé, utiliser les services par défaut
        return load_services()
    except Exception as e:
        print(f"Erreur lors du chargement des services pour le garage {garage_id}: {str(e)}")
        return load_services()

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
    print(f"\n[DEBUG] Envoi du message d'étape:")
    print(f"- Destinataire: {to_number}")
    print(f"- Index de l'étape: {step_index}")
    print(f"- Processus: {process[step_index].get('message', 'Pas de message')}")
    step = process[step_index]
    message = step['message']
    expected_answers = step['expected_answers']

    # Remplacer le nom du garage si présent
    if '{{garage_name}}' in message and to_number in user_data and 'selected_garage' in user_data[to_number]:
        garage_name = user_data[to_number]['selected_garage']['name']
        message = message.replace('{{garage_name}}', garage_name)
        print(f"[DEBUG] Nom du garage remplacé: {garage_name}")

    # Gérer les données dynamiques si présentes
    if 'dynamic_data' in step:
        # Nouvelle structure pour les services
        if 'services' in step['dynamic_data'] or 'services_file' in step['dynamic_data']:
            # Récupérer les services du garage sélectionné
            if to_number in user_data and 'selected_garage' in user_data[to_number]:
                garage_id = user_data[to_number]['selected_garage']['id']
                services = get_garage_services(garage_id)
            else:
                # Si aucun garage n'est sélectionné, utiliser les services par défaut
                services = load_services()

            # Remplacer les placeholders dans le message
            message = message.replace('{{services_list}}', format_services_list(services))
            # Remplacer les placeholders dans les réponses attendues
            if expected_answers == '{{services_ids}}':
                expected_answers = get_services_ids(services)
                # Stocker les réponses attendues dans user_data pour la validation
                if to_number in user_data:
                    user_data[to_number]['current_expected_answers'] = expected_answers

    # Si on a des réponses attendues spécifiques (pas free_text), créer des boutons ou une liste
    if expected_answers != 'free_text' and expected_answers != 'no_reply':
        url = f"https://graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/messages"
        headers = {
            "Authorization": f"Bearer {ACCESS_TOKEN}",
            "Content-Type": "application/json"
        }

        if len(expected_answers) <= 3:
            # Utiliser des boutons pour 3 options ou moins
            buttons = []
            for answer in expected_answers:
                # Pour les services, utiliser le nom du service comme titre
                if 'dynamic_data' in step and ('services' in step['dynamic_data'] or 'services_file' in step['dynamic_data']):
                    for service in services['services']:
                        if service['id'] == answer:
                            # Raccourcir le titre pour les boutons
                            title = f"{service['name']} ({service['duration']}min)"
                            if len(title) > 20:
                                title = f"{service['name'][:15]}... ({service['duration']}min)"
                            break
                else:
                    # Pour les choix génériques (1, 2, 3), utiliser des libellés explicites
                    title = answer
                    if answer == '1':
                        title = 'Prendre rendez-vous'
                    elif answer == '2':
                        title = 'Annuler un RDV'
                    elif answer == '3':
                        title = 'Autres'

                buttons.append({
                    "type": "reply",
                    "reply": {
                        "id": answer,
                        "title": title
                    }
                })

            payload = {
                "messaging_product": "whatsapp",
                "to": to_number,
                "type": "interactive",
                "interactive": {
                    "type": "button",
                    "body": {
                        "text": message
                    },
                    "action": {
                        "buttons": buttons
                    }
                }
            }
        else:
            # Utiliser une liste pour plus de 3 options
            sections = [{
                "title": "Services disponibles",
                "rows": []
            }]

            for answer in expected_answers:
                # Pour les services, utiliser le nom du service comme titre
                if 'dynamic_data' in step and ('services' in step['dynamic_data'] or 'services_file' in step['dynamic_data']):
                    for service in services['services']:
                        if service['id'] == answer:
                            # Pour les listes, on peut utiliser des titres plus longs
                            title = f"{service['name']} ({service['duration']} min)"
                            description = f"Durée estimée: {service['duration']} minutes"
                            break
                else:
                    # Pour les autres choix, utiliser le texte de la réponse
                    title = answer
                    if answer == '1':
                        title = 'Prendre rendez-vous'
                    elif answer == '2':
                        title = 'Annuler un rendez-vous'
                    elif answer == '3':
                        title = 'Autres'
                    description = ""

                sections[0]["rows"].append({
                    "id": answer,
                    "title": title,
                    "description": description
                })

            payload = {
                "messaging_product": "whatsapp",
                "to": to_number,
                "type": "interactive",
                "interactive": {
                    "type": "list",
                    "body": {
                        "text": message
                    },
                    "action": {
                        "button": "Choisir un service",
                        "sections": sections
                    }
                }
            }

        print("Envoi du message interactif:", payload)  # Debug
        response = requests.post(url, headers=headers, data=json.dumps(payload))
        print("Réponse envoi message:", response.status_code, response.json())
    else:
        # Pour free_text ou no_reply, envoyer un message normal
        send_message(to_number, message)

    return expected_answers

def send_message(to_number, message):
    print(f"\n[Message envoyé]: {message}")
    # Si c'est un message de créneaux, afficher la durée
    if "Voici les créneaux disponibles" in message:
        service_id = user_data.get('test_user', {}).get('data', {}).get('Service souhaité')
        try:
            # Utiliser les services du garage sélectionné
            if 'test_user' in user_data and 'selected_garage' in user_data['test_user']:
                garage_id = user_data['test_user']['selected_garage']['id']
                services = get_garage_services(garage_id)
            else:
                # Fallback aux services globaux
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

def get_future_appointments(sender):
    print(f"\n[DEBUG] Recherche des rendez-vous futurs:")
    print(f"- Client: {sender}")

    # Récupérer l'ID du garage sélectionné
    garage_id = None
    if sender in user_data and 'selected_garage' in user_data[sender]:
        garage_id = user_data[sender]['selected_garage']['id']
        print(f"- Garage ID: {garage_id}")

    if os.getenv('TEST_MODE') == 'True':
        # En mode test, retourner des rendez-vous fictifs
        today = datetime.now()
        appointments = []
        for i in range(3):
            start_time = today + timedelta(days=i+1, hours=9)
            end_time = start_time + timedelta(hours=2)
            appointments.append({
                'id': f"test_rdv_{i}",
                'start': start_time,
                'end': end_time,
                'summary': f"RDV Garage avec {user_data[sender]['data'].get('Nom complet', 'Client')}",
                'description': "Service: Révision (120 min)\nVéhicule: Renault Clio 2019"
            })
        return appointments

    # En mode production, chercher dans Google Calendar
    timezone = pytz.timezone(TIMEZONE)
    now = datetime.now(timezone)

    # Utiliser le service et le calendar_id spécifiques au garage
    if garage_id:
        calendar_info = get_garage_calendar_service(garage_id)
        specific_calendar_service = calendar_info['service']
        specific_calendar_id = calendar_info['calendar_id']
    else:
        specific_calendar_service = calendar_service
        specific_calendar_id = CALENDAR_ID

    # Rechercher les événements futurs
    events_result = specific_calendar_service.events().list(
        calendarId=specific_calendar_id,
        timeMin=now.isoformat(),
        maxResults=10,
        singleEvents=True,
        orderBy='startTime'
    ).execute()

    # Filtrer les événements pour ne garder que ceux du sender
    appointments = []
    for event in events_result.get('items', []):
        # Vérifier si l'événement contient le numéro WhatsApp du sender
        if sender in event.get('description', ''):
            start = datetime.fromisoformat(event['start']['dateTime'].replace('Z', '+00:00'))
            end = datetime.fromisoformat(event['end']['dateTime'].replace('Z', '+00:00'))
            appointments.append({
                'id': event['id'],
                'start': start,
                'end': end,
                'summary': event['summary'],
                'description': event['description']
            })

    return appointments

def send_appointment_buttons(sender, appointments):
    print(f"\n[DEBUG] Envoi des boutons de rendez-vous:")
    print(f"- Client: {sender}")
    print(f"- Nombre de rendez-vous: {len(appointments)}")
    if not appointments:
        send_message(sender, "Vous n'avez aucun rendez-vous à venir.")
        return False

    url = f"https://graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    # Créer les sections pour la liste
    sections = [{
        "title": "Vos rendez-vous",
        "rows": []
    }]

    # Ajouter chaque rendez-vous à la liste
    for idx, appointment in enumerate(appointments, 1):
        # Extraire les informations du rendez-vous
        start_time = appointment['start']
        end_time = appointment['end']

        # Extraire le service de la description
        service_info = "Service non spécifié"
        vehicle_info = ""
        if 'description' in appointment:
            for line in appointment['description'].split('\n'):
                if line.startswith('- Service :'):
                    service_info = line.replace('- Service :', '').strip()
                elif line.startswith('- Véhicule :'):
                    vehicle_info = line.replace('- Véhicule :', '').strip()

        # Calculer la durée
        duration = (end_time - start_time).total_seconds() / 60

        sections[0]["rows"].append({
            "id": appointment['id'],
            "title": f"RDV {idx}",
            "description": f"{format_date_fr(start_time)} - {service_info} - {vehicle_info}"
        })

    payload = {
        "messaging_product": "whatsapp",
        "to": sender,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {
                "text": "Quel rendez-vous souhaitez-vous annuler ?"
            },
            "action": {
                "button": "Choisir RDV",  # Raccourci pour respecter la limite de 20 caractères
                "sections": sections
            }
        }
    }

    print("Envoi de la liste des rendez-vous:", payload)  # Debug
    response = requests.post(url, headers=headers, data=json.dumps(payload))
    print("Réponse envoi message:", response.status_code, response.json())
    return True

def send_confirmation_buttons(sender, appointment_id):
    print(f"\n[DEBUG] Envoi des boutons de confirmation:")
    print(f"- Client: {sender}")
    print(f"- ID du rendez-vous: {appointment_id}")
    url = f"https://graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": sender,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {
                "text": "Êtes-vous sûr de vouloir annuler ce rendez-vous ?"
            },
            "action": {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {
                            "id": f"confirm_cancel_{appointment_id}",
                            "title": "Oui, annuler"
                        }
                    },
                    {
                        "type": "reply",
                        "reply": {
                            "id": "cancel_cancel",
                            "title": "Non, garder"
                        }
                    }
                ]
            }
        }
    }

    response = requests.post(url, headers=headers, data=json.dumps(payload))
    print("Réponse envoi confirmation:", response.status_code, response.json())

def get_calendar_service():
    """Initialise et retourne le service Google Calendar"""
    try:
        credentials = service_account.Credentials.from_service_account_file(
            CREDENTIALS_FILE_CALENDAR,
            scopes=['https://www.googleapis.com/auth/calendar']
        )
        service = build('calendar', 'v3', credentials=credentials)
        return service
    except Exception as e:
        print(f"Erreur lors de l'initialisation du service Calendar: {e}")
        return None

def cancel_appointment(appointment_id, sender=None):
    print(f"\n[DEBUG] Tentative d'annulation du rendez-vous:")
    print(f"- ID du rendez-vous: {appointment_id}")

    # Récupérer l'ID du garage sélectionné si sender est fourni
    garage_id = None
    if sender and sender in user_data and 'selected_garage' in user_data[sender]:
        garage_id = user_data[sender]['selected_garage']['id']
        print(f"- Garage ID: {garage_id}")

    try:
        # Utiliser le service et le calendar_id spécifiques au garage
        if garage_id:
            calendar_info = get_garage_calendar_service(garage_id)
            specific_calendar_service = calendar_info['service']
            specific_calendar_id = calendar_info['calendar_id']
        else:
            specific_calendar_service = calendar_service
            specific_calendar_id = CALENDAR_ID

        print(f"[DEBUG] Service Calendar: {specific_calendar_service}")
        print(f"[DEBUG] Calendar ID: {specific_calendar_id}")

        if specific_calendar_service:
            specific_calendar_service.events().delete(
                calendarId=specific_calendar_id,
                eventId=appointment_id
            ).execute()
            return True
        return False
    except Exception as e:
        print(f"Erreur lors de l'annulation du rendez-vous: {e}")
        return False

def test_cancel_appointment():
    """Test du processus d'annulation de rendez-vous"""
    # Simuler un numéro de téléphone
    test_phone = "33600000000"

    # Simuler un rendez-vous existant avec des objets datetime
    from datetime import datetime, timedelta

    start_time = datetime(2024, 3, 20, 10, 0)  # 20 mars 2024 à 10h00
    end_time = start_time + timedelta(hours=1)  # 1 heure plus tard

    test_appointment = {
        'id': 'test_appointment_123',
        'start': start_time,
        'end': end_time,
        'description': '- Service : Révision\n- Véhicule : Renault Clio 2019'
    }

    # Simuler la liste des rendez-vous
    test_appointments = [test_appointment]

    print("\n=== Test du processus d'annulation ===")

    # 1. Simuler l'envoi de la liste des rendez-vous
    print("\n1. Envoi de la liste des rendez-vous")
    send_appointment_buttons(test_phone, test_appointments)

    # 2. Simuler la sélection d'un rendez-vous
    print("\n2. Sélection d'un rendez-vous")
    list_reply = {
        "messaging_product": "whatsapp",
        "status": "sent",
        "to": test_phone,
        "type": "interactive",
        "interactive": {
            "type": "list_reply",
            "list_reply": {
                "id": test_appointment['id'],
                "title": "RDV 1"
            }
        }
    }

    # Simuler la réponse du webhook pour la sélection
    webhook_response = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "123456789",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp_business_account",
                    "metadata": {
                        "display_phone_number": "33600000000",
                        "phone_number_id": "123456789"
                    },
                    "contacts": [{
                        "profile": {
                            "name": "Test User"
                        },
                        "wa_id": test_phone
                    }],
                    "messages": [{
                        "from": test_phone,
                        "id": "wamid.123",
                        "timestamp": "1234567890",
                        "type": "interactive",
                        "interactive": list_reply["interactive"]
                    }]
                }
            }]
        }]
    }

    # 3. Simuler la confirmation d'annulation
    print("\n3. Confirmation d'annulation")
    button_reply = {
        "messaging_product": "whatsapp",
        "status": "sent",
        "to": test_phone,
        "type": "interactive",
        "interactive": {
            "type": "button_reply",
            "button_reply": {
                "id": f"confirm_cancel_{test_appointment['id']}",
                "title": "Oui, annuler"
            }
        }
    }

    # Simuler la réponse du webhook pour la confirmation
    webhook_response_confirm = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "123456789",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp_business_account",
                    "metadata": {
                        "display_phone_number": "33600000000",
                        "phone_number_id": "123456789"
                    },
                    "contacts": [{
                        "profile": {
                            "name": "Test User"
                        },
                        "wa_id": test_phone
                    }],
                    "messages": [{
                        "from": test_phone,
                        "id": "wamid.123",
                        "timestamp": "1234567890",
                        "type": "interactive",
                        "interactive": button_reply["interactive"]
                    }]
                }
            }]
        }]
    }

    # Exécuter les tests
    print("\nExécution des tests...")

    # Test de la sélection du rendez-vous
    print("\nTest de la sélection du rendez-vous:")
    with app.test_request_context(json=webhook_response):
        webhook()

    # Test de la confirmation d'annulation
    print("\nTest de la confirmation d'annulation:")
    with app.test_request_context(json=webhook_response_confirm):
        webhook()

    print("\n=== Fin du test ===")

def test_conversation():
    """Test du processus de création de rendez-vous"""
    # Simuler un numéro de téléphone
    test_phone = "33600000000"

    # Simuler les messages de l'utilisateur
    test_messages = [
        "Je veux prendre un rendez-vous",
        "Révision",
        "Renault Clio 2019",
        "Ok",
        "20 juin 2025",
        "10:00"
    ]

    print("\n=== Test du processus de création ===")

    # Simuler chaque message
    for message in test_messages:
        print(f"\nMessage: {message}")

        # Créer la structure du message
        webhook_data = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "123456789",
                "changes": [{
                    "value": {
                        "messaging_product": "whatsapp_business_account",
                        "metadata": {
                            "display_phone_number": "33600000000",
                            "phone_number_id": "123456789"
                        },
                        "contacts": [{
                            "profile": {
                                "name": "Test User"
                            },
                            "wa_id": test_phone
                        }],
                        "messages": [{
                            "from": test_phone,
                            "id": "wamid.123",
                            "timestamp": "1234567890",
                            "type": "text",
                            "text": {
                                "body": message
                            }
                        }]
                    }
                }]
            }]
        }

        # Envoyer le message au webhook
        webhook(webhook_data)

    print("\n=== Fin du test ===")

def save_to_google_sheets(sender, process_type, additional_data=None):
    """
    Enregistre les données dans Google Sheets
    Args:
        sender: Le numéro de téléphone de l'expéditeur
        process_type: Le type de processus ('creation', 'annulation', 'autres')
        additional_data: Dictionnaire optionnel contenant des données supplémentaires à enregistrer
    """
    print(f"[DEBUG] Tentative d'enregistrement dans Google Sheets:")
    print(f"- Process type: {process_type}")
    print(f"- Sender: {sender}")
    print(f"- Additional data: {additional_data}")

    # Obtenir la date et l'heure actuelles
    now = datetime.now()
    date_heure = now.strftime("%d/%m/%Y %H:%M:%S")

    # Déterminer le type de demande (1, 2 ou 3)
    type_demande = None
    if process_type == 'creation':
        type_demande = 'creation'
    elif process_type == 'annulation':
        type_demande = 'annulation'
    elif process_type == 'autres':
        type_demande = 'autres'

    # Construction de la ligne à enregistrer
    record = [
        sender,  # Numéro de téléphone WhatsApp
        type_demande,  # Type de demande (1, 2 ou 3)
        date_heure,  # Date et heure d'enregistrement
    ]

    # Ajouter les données de base
    for key, value in user_data[sender]['data'].items():
        record.append(value)

    # Ajouter le type de processus
    record.append(process_type)

    # Ajouter les données supplémentaires si présentes
    if additional_data:
        for key, value in additional_data.items():
            record.append(value)

    print(f"[DEBUG] Données à enregistrer: {record}")
    print(f"[DEBUG] Credentials file: {CREDENTIALS_FILE}")

    # Ajouter une ligne dans Google Sheets
    try:
        print(f"[DEBUG] Connexion à Google Sheets...")
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
        client = gspread.authorize(creds)
        sheet = client.open("leads whatsapp").sheet1
        print(f"[DEBUG] Ajout de la ligne dans Google Sheets...")
        sheet.append_row(record)
        print(f"✅ Lead ajouté dans Google Sheet : {record}")
        return True
    except Exception as e:
        print(f"❌ Erreur lors de l'ajout dans Google Sheets: {str(e)}")
        print(f"❌ Type d'erreur: {type(e)}")
        import traceback
        print(f"❌ Traceback: {traceback.format_exc()}")
        return False

def send_final_message(sender, text):
    """Envoie le message final avec les options pour une nouvelle demande"""
    url = f"https://graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    # Envoyer d'abord le message de confirmation
    send_message(sender, text)

    # Envoyer ensuite le message avec les boutons
    payload = {
        "messaging_product": "whatsapp",
        "to": sender,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {
                "text": "Souhaitez-vous faire une autre demande ?"
            },
            "action": {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {
                            "id": "new_request",
                            "title": "Nouvelle demande"
                        }
                    },
                    {
                        "type": "reply",
                        "reply": {
                            "id": "no_new_request",
                            "title": "Terminer"
                        }
                    }
                ]
            }
        }
    }

    print("[DEBUG] Envoi du message final avec options")
    response = requests.post(url, headers=headers, data=json.dumps(payload))
    print("Réponse envoi message final:", response.status_code, response.json())

def handle_final_response(sender, text):
    """Gère la réponse au message final"""
    print(f"[DEBUG] Gestion de la réponse finale - Réponse reçue: {text}")
    if text == "new_request":
        print("[DEBUG] Nouvelle demande détectée - Réinitialisation du bot")
        # Réinitialiser le bot
        if sender in user_data:
            del user_data[sender]
        # Initialiser un nouvel utilisateur
        user_data[sender] = {
            'state': 'initial',
            'current_step': 0,
            'data': {},
            'last_activity': datetime.now()
        }
        # Envoyer le message de sélection de garage plutôt que le message initial du processus
        send_initial_garage_message(sender)
    elif text == "no_new_request":
        print("[DEBUG] Fin de conversation détectée")
        # Effacer la conversation
        if sender in user_data:
            del user_data[sender]

def handle_creation_process(sender, state, text, message):
    """Gère le processus de création de rendez-vous"""
    print(f"[DEBUG] Gestion du processus de création - État: {state}")

    if state == 'initial':
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

        # Récupérer l'ID du garage sélectionné
        garage_id = None
        if 'selected_garage' in user_data[sender]:
            garage_id = user_data[sender]['selected_garage']['id']

        # Récupérer les informations du service
        service_id = user_data[sender]['data'].get('Service souhaité')

        # Utiliser les services du garage sélectionné
        if garage_id:
            services = get_garage_services(garage_id)
        else:
            # Fallback aux services globaux
            with open('services.json', 'r') as f:
                services = json.load(f)

        # Trouver le service correspondant
        service_duration = None
        service_name = None
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

        slots = find_available_slots(start_date, service_duration, garage_id=garage_id)
        if not slots:
            send_message(sender, "Désolé, aucun créneau n'est disponible à partir de cette date. Merci d'en proposer une autre.")
            send_date_buttons(sender)  # Renvoyer les boutons
            return "OK", 200

        # Proposer les créneaux à l'utilisateur avec une liste
        url = f"https://graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/messages"
        headers = {
            "Authorization": f"Bearer {ACCESS_TOKEN}",
            "Content-Type": "application/json"
        }

        # Créer les sections pour la liste
        sections = [{
            "title": "Créneaux disponibles",
            "rows": []
        }]

        # Ajouter chaque créneau à la liste
        for idx, (slot_start, slot_end) in enumerate(slots, 1):
            # Formater les horaires
            start_time = format_date_fr(slot_start)
            end_time = format_date_fr(slot_end)

            # Calculer la durée
            duration = (slot_end - slot_start).total_seconds() / 60

            sections[0]["rows"].append({
                "id": str(idx),
                "title": f"C Créneau {idx}",
                "description": f"{start_time} - {end_time} ({int(duration)} min)"
            })

        payload = {
            "messaging_product": "whatsapp",
            "to": sender,
            "type": "interactive",
            "interactive": {
                "type": "list",
                "body": {
                    "text": "Voici les créneaux disponibles :"
                },
                "action": {
                    "button": "Choisir un créneau",
                    "sections": sections
                }
            }
        }

        print("Envoi de la liste des créneaux:", payload)  # Debug
        response = requests.post(url, headers=headers, data=json.dumps(payload))
        print("Réponse envoi message:", response.status_code, response.json())

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

        # Utiliser les services du garage sélectionné
        if 'selected_garage' in user_data[sender]:
            garage_id = user_data[sender]['selected_garage']['id']
            services = get_garage_services(garage_id)
        else:
            # Fallback aux services globaux
            with open('services.json', 'r') as f:
                services = json.load(f)

        # Trouver le service correspondant
        service_info = None
        for service in services['services']:
            if service['id'] == service_id:
                # Stocker les informations du service dans user_data
                user_data[sender]['service_info'] = {
                    'name': service['name'],
                    'duration': int(service['duration'])
                }
                service_info = user_data[sender]['service_info']
                break

        # Vérifier que nous avons bien trouvé le service
        if service_info is None:
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

        # Stocker les informations du rendez-vous dans user_data
        user_data[sender]['data'].update({
            'Date RDV': format_date_fr(slot_start),
            'Heure fin RDV': format_date_fr(slot_end),
            'Service': service_info.get('name'),
            'Durée service': f"{service_info.get('duration')} min"
        })

        # Enregistrer dans Google Sheets
        save_to_google_sheets(sender, 'creation', {
            'Date RDV': format_date_fr(slot_start),
            'Heure fin RDV': format_date_fr(slot_end),
            'Service': service_info.get('name'),
            'Durée service': f"{service_info.get('duration')} min"
        })

        text_message = f"Votre rendez-vous est confirmé ! 📅\nLien Google Calendar : {link}"
        send_final_message(sender, text_message)
        user_data[sender]['state'] = 'final'
        return "OK", 200

    if state == 'final':
        print(f"[DEBUG] État final - Réponse reçue: {text}")
        if message.get("interactive") and message["interactive"].get("type") == "button_reply":
            button_id = message["interactive"]["button_reply"]["id"]
            print(f"[DEBUG] Button ID reçu: {button_id}")
            handle_final_response(sender, button_id)
        return "OK", 200

    return "OK", 200

def handle_cancellation_process(sender, state, text, message):
    """Gère le processus d'annulation de rendez-vous"""
    print(f"[DEBUG] Gestion du processus d'annulation - État: {state}")

    if state == "initial":
        appointments = get_future_appointments(sender)
        send_appointment_buttons(sender, appointments)
        user_data[sender]['state'] = 'ask_appointment_to_cancel'
        return "OK", 200

    elif state == "ask_appointment_to_cancel":
        # L'utilisateur a déjà vu la liste des rendez-vous
        if message.get("interactive"):
            interactive_type = message["interactive"].get("type")
            if interactive_type == "list_reply":
                # L'utilisateur a sélectionné un rendez-vous
                appointment_id = message["interactive"]["list_reply"]["id"]
                # Envoyer les boutons de confirmation
                send_confirmation_buttons(sender, appointment_id)
                # Sauvegarder l'ID du rendez-vous dans la session
                user_data[sender]["pending_cancel_id"] = appointment_id
                user_data[sender]["state"] = "pending_cancel_confirmation"
                return "OK", 200
            elif interactive_type == "button_reply":
                button_id = message["interactive"]["button_reply"]["id"]
                send_confirmation_buttons(sender, appointment_id)
                # Sauvegarder l'ID du rendez-vous dans la session
                user_data[sender]["pending_cancel_id"] = appointment_id
                user_data[sender]["state"] = "pending_cancel_confirmation"
                return "OK", 200

    elif state == "pending_cancel_confirmation":
        if message.get("interactive") and message["interactive"].get("type") == "button_reply":
            button_id = message["interactive"]["button_reply"]["id"]
            print(f"[DEBUG] Button id is {button_id}")
            if button_id.startswith("confirm_cancel"):
                # L'utilisateur a confirmé l'annulation
                appointment_id = user_data[sender]["pending_cancel_id"]
                print(f"[DEBUG] Appointment id is {appointment_id}")
                if cancel_appointment(appointment_id, sender):
                    # Stocker les informations de l'annulation dans user_data
                    user_data[sender]['data'].update({
                        'Appointment ID': appointment_id,
                        'Status': 'Annulé'
                    })
                    # Enregistrer l'annulation dans Google Sheets
                    save_to_google_sheets(sender, 'annulation', {
                        'Appointment ID': appointment_id,
                        'Status': 'Annulé'
                    })
                    text_message = "✅ Votre rendez-vous a été annulé avec succès."
                else:
                    text_message = "❌ Désolé, une erreur s'est produite lors de l'annulation du rendez-vous."
                # Nettoyer la session
                user_data[sender].pop("pending_cancel_id", None)
                # Envoyer le message final
                send_final_message(sender, text_message)
                user_data[sender]['state'] = 'final'
                return "OK", 200
            elif button_id.startswith("cancel_cancel"):
                # L'utilisateur a annulé l'annulation
                # Stocker les informations dans user_data
                user_data[sender]['data'].update({
                    'Status': 'Annulation annulée'
                })
                # Enregistrer l'annulation annulée dans Google Sheets
                save_to_google_sheets(sender, 'annulation', {
                    'Status': 'Annulation annulée'
                })
                # Nettoyer la session
                user_data[sender].pop("pending_cancel_id", None)
                text_message = "✅ L'annulation a été annulée. Votre rendez-vous est maintenu."
                # Envoyer le message final
                send_final_message(sender, text_message)
                user_data[sender]['state'] = 'final'
                return "OK", 200
        return "OK", 200

    if state == 'final':
        print(f"[DEBUG] État final - Réponse reçue: {text}")
        if message.get("interactive") and message["interactive"].get("type") == "button_reply":
            button_id = message["interactive"]["button_reply"]["id"]
            print(f"[DEBUG] Button ID reçu: {button_id}")
            handle_final_response(sender, button_id)
        return "OK", 200

    return "OK", 200

def handle_other_process(sender, state):
    """Gère le processus d'autres"""
    print(f"[DEBUG] Gestion du processus d'autres - État: {state}")

    # Stocker les informations dans user_data
    user_data[sender]['data'].update({
        'Status': 'En attente de traitement'
    })

    # Enregistrer la demande dans Google Sheets
    save_to_google_sheets(sender, 'autres', {
        'Status': 'En attente de traitement'
    })

    text_message = "Merci votre message a été transmis à l'équipe, on reviendra vers vous dans les plus brefs délais"
    # Envoyer le message final
    send_final_message(sender, text_message)
    user_data[sender]['state'] = 'final'
    return "OK", 200

def send_initial_garage_message(sender):
    """Envoie le message initial demandant le pseudo du garage"""
    print(f"\n[DEBUG] Envoi du message initial de sélection de garage à {sender}")
    message = "Bienvenue ! Pour commencer, veuillez indiquer le pseudo du garage avec lequel vous souhaitez prendre rendez-vous."
    print(f"[DEBUG] Message à envoyer:\n{message}")
    send_message(sender, message)

def send_garage_selection_message(sender):
    """Envoie la liste des garages disponibles"""
    print(f"\n[DEBUG] Envoi de la liste des garages à {sender}")
    garages = load_garages()
    message = "Voici la liste des garages disponibles :\n\n"
    message += format_garages_list(garages)
    print(f"[DEBUG] Message à envoyer:\n{message}")
    send_message(sender, message)

def handle_garage_selection(sender, text):
    """Gère la sélection du garage par l'utilisateur et retourne les informations du garage"""
    print(f"\n[DEBUG] Gestion de la sélection du garage:")
    print(f"- Sender: {sender}")
    print(f"- Texte reçu: {text}")

    # Supprimer le @ si présent
    pseudo = text.replace('@', '').strip()
    print(f"[DEBUG] Pseudo nettoyé: {pseudo}")

    garage = get_garage_by_pseudo(pseudo)

    if garage:
        print(f"[DEBUG] Garage trouvé: {garage['name']}")
        # Envoyer un message de confirmation
        confirmation_message = f"Vous avez sélectionné le garage : {garage['name']} ({garage['city']})"
        print(f"[DEBUG] Envoi du message de confirmation: {confirmation_message}")
        send_message(sender, confirmation_message)

        # Envoyer un bouton de confirmation
        print("[DEBUG] Préparation des boutons de confirmation")
        url = f"https://graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/messages"
        headers = {
            "Authorization": f"Bearer {ACCESS_TOKEN}",
            "Content-Type": "application/json"
        }
        payload = {
            "messaging_product": "whatsapp",
            "to": sender,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {
                    "text": "Voulez-vous continuer avec ce garage ?"
                },
                "action": {
                    "buttons": [
                        {
                            "type": "reply",
                            "reply": {
                                "id": "confirm_garage",
                                "title": "OK"
                            }
                        },
                        {
                            "type": "reply",
                            "reply": {
                                "id": "change_garage",
                                "title": "Changer de garage"
                            }
                        }
                    ]
                }
            }
        }
        print("[DEBUG] Envoi des boutons de confirmation")
        response = requests.post(url, headers=headers, data=json.dumps(payload))
        print(f"[DEBUG] Réponse envoi confirmation: {response.status_code} - {response.json()}")
        return garage
    else:
        print("[DEBUG] Garage non trouvé, envoi du message d'erreur et de la liste")
        send_message(sender, "Désolé, je ne trouve pas ce garage. Voici la liste des garages disponibles :")
        send_garage_selection_message(sender)
        # Réinitialiser l'état de l'utilisateur pour qu'il puisse réessayer
        if sender in user_data:
            user_data[sender]['state'] = 'initial'
        return None

def load_garages():
    """Charge les garages depuis le fichier garages.json"""
    print("\n[DEBUG] Chargement des garages depuis garages.json")
    try:
        with open('garages.json', 'r') as f:
            garages = json.load(f)
            print(f"[DEBUG] {len(garages['garages'])} garages chargés")
            return garages
    except Exception as e:
        print(f"[ERROR] Erreur lors du chargement des garages: {str(e)}")
        return {"garages": []}

def format_garages_list(garages):
    """Formate la liste des garages pour l'affichage"""
    print("\n[DEBUG] Formatage de la liste des garages")
    formatted_list = []
    for garage in garages['garages']:
        formatted_line = f"🏪 {garage['name']} ({garage['city']}) - @{garage['pseudo']}"
        formatted_list.append(formatted_line)
        print(f"[DEBUG] Garage formaté: {formatted_line}")
    return "\n".join(formatted_list)

def get_garage_by_pseudo(pseudo):
    """Récupère un garage par son pseudo"""
    print(f"\n[DEBUG] Recherche du garage avec le pseudo: {pseudo}")
    garages = load_garages()
    for garage in garages['garages']:
        if garage['pseudo'].lower() == pseudo.lower():
            print(f"[DEBUG] Garage trouvé: {garage['name']} ({garage['city']})")
            return garage
    print("[DEBUG] Aucun garage trouvé avec ce pseudo")
    return None

def test_max_appointments_per_slot():
    """Test de la fonctionnalité de nombre maximal de rendez-vous par créneau"""
    print("\n=== Test de la limitation du nombre de rendez-vous par créneau ===")

    # Paramètres de test
    start_date = datetime.now().date()
    service_duration = 60  # 60 minutes
    garage_id = "garage1"  # Utiliser le garage1 qui a max_appointments_per_slot = 2

    # Charger les paramètres du garage
    garages = load_garages()
    garage = None
    for g in garages['garages']:
        if g['id'] == garage_id:
            garage = g
            break

    if not garage:
        print("[ERROR] Garage de test non trouvé")
        return

    max_appointments = garage.get('max_appointments_per_slot', 1)
    print(f"[INFO] Garage de test: {garage['name']}")
    print(f"[INFO] Nombre maximal de rendez-vous par créneau: {max_appointments}")
    print(f"[INFO] Type de max_appointments_per_slot: {type(max_appointments)}")

    # Tester manuellement la comparaison
    for count in range(0, 4):
        is_available = count < max_appointments
        print(f"[TEST] {count} < {max_appointments} = {is_available}")

        # Tester avec conversion explicite en int
        is_available_int = int(count) < int(max_appointments)
        print(f"[TEST] int({count}) < int({max_appointments}) = {is_available_int}")

    print("\n=== Fin du test ===")

# === RUN APP ===
if __name__ == '__main__':
    import sys

    if len(sys.argv) > 1:
        if sys.argv[1] == "--test-cancel":
            print("Lancement du test d'annulation...")
            test_cancel_appointment()
        elif sys.argv[1] == "--test-create":
            print("Lancement du test de création...")
            test_conversation()
        elif sys.argv[1] == "--test-max-slots":
            print("Lancement du test de limitation des rendez-vous par créneau...")
            try:
                test_max_appointments_per_slot()
            except Exception as e:
                print(f"[ERROR] Exception lors du test: {str(e)}")
    else:
        app.run(host='0.0.0.0', port=5000)
