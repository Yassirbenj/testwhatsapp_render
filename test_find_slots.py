import json
import os
from datetime import datetime, timedelta, time
import pytz

# Define mock classes and functions to bypass Google API calls
class MockCalendarService:
    def calendars(self):
        return MockCalendarAPI()

    def events(self):
        return MockEventsAPI()

    def freebusy(self):
        return MockFreeBusyAPI()

class MockCalendarAPI:
    def get(self, calendarId):
        return MockExecutable({"summary": "Test Calendar"})

    def list(self):
        return MockExecutable({"items": [{"id": "test_calendar@gmail.com"}]})

class MockEventsAPI:
    def list(self, calendarId, timeMin, timeMax, singleEvents, orderBy):
        today = datetime.now()
        event_date = datetime(today.year, 5, 16, 10, 0).isoformat() + 'Z'
        event_end = datetime(today.year, 5, 16, 12, 0).isoformat() + 'Z'

        return MockExecutable({
            "items": [
                {
                    "summary": "RDV Garage avec ddd",
                    "start": {"dateTime": event_date},
                    "end": {"dateTime": event_end}
                }
            ]
        })

    def insert(self, calendarId, body):
        return MockExecutable({"htmlLink": "https://calendar.google.com/mock-link"})

class MockFreeBusyAPI:
    def query(self, body):
        today = datetime.now()
        busy_start = datetime(today.year, 5, 16, 10, 0).isoformat() + 'Z'
        busy_end = datetime(today.year, 5, 16, 12, 0).isoformat() + 'Z'

        return MockExecutable({
            "calendars": {
                "test_calendar@gmail.com": {
                    "busy": [
                        {"start": busy_start, "end": busy_end}
                    ]
                }
            }
        })

class MockExecutable:
    def __init__(self, result):
        self.result = result

    def execute(self):
        return self.result

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

def get_garage_calendar_service(garage_id):
    """Version simulée de la fonction get_garage_calendar_service"""
    mock_service = MockCalendarService()
    return {
        'service': mock_service,
        'calendar_id': 'test_calendar@gmail.com'
    }

def find_available_slots(start_date, service_duration, num_days=5, garage_id=None):
    print(f"\n[DEBUG] Recherche de créneaux disponibles:")
    print(f"- Date de début: {start_date}")
    print(f"- Durée du service: {service_duration} minutes")
    print(f"- Nombre de jours: {num_days}")
    print(f"- Garage ID: {garage_id}")

    # Code pour le mode production
    timezone = pytz.timezone('Africa/Casablanca')
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
        specific_calendar_service = MockCalendarService()
        specific_calendar_id = 'test_calendar@gmail.com'
        closing_hour = 18  # Valeur par défaut si pas de garage spécifié
        working_hours = [9, 10, 11, 14, 15, 16, 17]  # Valeurs par défaut
        max_appointments_per_slot = 1  # Valeur par défaut

    # Vérifier d'abord si le calendrier existe
    try:
        calendar_info = specific_calendar_service.calendars().get(calendarId=specific_calendar_id).execute()
        print(f"[INFO] Calendrier trouvé: {calendar_info.get('summary', specific_calendar_id)}")
    except Exception as e:
        print(f"[WARNING] Calendrier non trouvé: {specific_calendar_id}. Erreur: {str(e)}")
        return []

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

        # Nous devons déterminer quels événements sont des blocages (non-RDV) et lesquels sont des RDV normaux
        # Créer un dictionnaire pour identifier les événements de blocage (non-RDV)
        blocking_events = {}
        for event in events:
            if 'dateTime' in event['start'] and 'dateTime' in event['end']:
                event_start = event['start']['dateTime']
                event_end = event['end']['dateTime']
                summary = event.get('summary', '').lower()

                # On considère comme "blocage" les événements qui ne sont pas des RDV Garage
                # ou qui contiennent des mots-clés spécifiques
                is_rdv_garage = summary.startswith('rdv garage')
                is_blocking_keyword = any(
                    keyword in summary.lower() for keyword in ['bloqué', 'blocage', 'indispo', 'fermeture']
                )

                # Un événement est un blocage s'il n'est PAS un RDV Garage ET qu'il contient un mot-clé de blocage
                # OU si c'est explicitement un blocage (avec un mot-clé)
                is_blocking = (not is_rdv_garage and not "rendez-vous" in summary.lower()) or is_blocking_keyword

                print(f"[DEBUG] Analyse de l'événement: {summary}")
                print(f"[DEBUG] Est un RDV Garage: {is_rdv_garage}")
                print(f"[DEBUG] Contient mot-clé de blocage: {is_blocking_keyword}")
                print(f"[DEBUG] Est un blocage: {is_blocking}")

                if is_blocking:
                    key = f"{event_start}_{event_end}"
                    blocking_events[key] = True
                    print(f"[DEBUG] Événement de blocage détecté: {summary} - {event_start} à {event_end}")

        # Filtrer les busy_times pour ne garder que les événements de blocage
        filtered_busy_times = []

        print(f"[DEBUG] Busy times avant filtrage: {len(busy_times)}")
        for busy in busy_times:
            busy_start = busy['start']
            busy_end = busy['end']
            key = f"{busy_start}_{busy_end}"

            # Si c'est un événement de blocage, le conserver
            if key in blocking_events:
                filtered_busy_times.append(busy)
                print(f"[DEBUG] Gardé comme busy: {busy_start} à {busy_end} (événement de blocage)")
            else:
                # Convertir en datetime pour vérifier si c'est un créneau de RDV
                busy_start_dt = datetime.fromisoformat(busy_start.replace('Z', '+00:00'))
                busy_start_local = busy_start_dt.astimezone(timezone)
                slot_key = busy_start_local.strftime('%Y-%m-%d-%H')

                # Créer un dictionnaire pour compter le nombre de rendez-vous par créneau horaire
                slot_counts = {'2025-05-16-10': 1}  # Simuler un rendez-vous existant

                is_appointment_slot = slot_key in slot_counts

                if is_appointment_slot:
                    # C'est un créneau de RDV, on l'ignore car il est géré par slot_counts
                    print(f"[DEBUG] Ignoré de busy_times: {busy_start} à {busy_end} (créneau RDV géré par compteur)")
                else:
                    # Ce n'est pas un créneau de RDV connu, donc on le considère comme busy
                    filtered_busy_times.append(busy)
                    print(f"[DEBUG] Gardé comme busy: {busy_start} à {busy_end} (non identifié)")

        print(f"[DEBUG] Busy times après filtrage: {len(filtered_busy_times)}")
        busy_times = filtered_busy_times

        # Parcourir les jours et les heures pour trouver des créneaux disponibles
        slots_checked = 0
        slots_available = 0
        slots_rejected_count = 0
        slots_rejected_overlap = 0

        # Créer un dictionnaire pour compter le nombre de rendez-vous par créneau horaire
        slot_counts = {'2025-05-16-10': 1}  # Simuler un rendez-vous existant

        print(f"[DEBUG] Nombre de rendez-vous par créneau: {slot_counts}")
        print(f"[DEBUG] Nombre maximum de rendez-vous par créneau autorisé: {max_appointments_per_slot}")

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

                        # Debug des busy_times
                        print(f"[DEBUG] Vérification de chevauchement pour {local_start.strftime('%Y-%m-%d %H:%M')}")
                        has_overlap = False
                        for busy in busy_times:
                            cond1 = busy['start'] <= start_utc < busy['end']
                            cond2 = busy['start'] < end_utc <= busy['end']
                            cond3 = start_utc <= busy['start'] and end_utc >= busy['end']
                            current_overlap = cond1 or cond2 or cond3
                            if current_overlap:
                                has_overlap = True
                                print(f"[DEBUG] Chevauchement détecté: {busy['start']} à {busy['end']}")
                                print(f"[DEBUG] Conditions: start_in_busy={cond1}, end_in_busy={cond2}, busy_in_slot={cond3}")

                        overlapping = has_overlap

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
        return []

def test_find_slots():
    """Test the find_available_slots function"""
    print("\n=== Test de la fonction find_available_slots ===")

    # Set up test parameters
    start_date = datetime.now().date()
    service_duration = 60
    garage_id = "garage1"  # Using garage1 which has max_appointments_per_slot = 2

    # Run the test
    slots = find_available_slots(start_date, service_duration, num_days=5, garage_id=garage_id)

    # Print the results
    if slots:
        print(f"\n[SUCCESS] {len(slots)} créneaux disponibles trouvés:")
        for i, (start, end) in enumerate(slots, 1):
            print(f"{i}. {start.strftime('%Y-%m-%d %H:%M')} - {end.strftime('%Y-%m-%d %H:%M')}")
    else:
        print("\n[FAILURE] Aucun créneau disponible trouvé")

    print("\n=== Fin du test ===")

if __name__ == "__main__":
    test_find_slots()
