import json

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

def test_max_appointments_per_slot():
    """Test de la fonctionnalité de nombre maximal de rendez-vous par créneau"""
    print("\n=== Test de la limitation du nombre de rendez-vous par créneau ===")

    # Paramètres de test
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

    # Créer un dictionnaire simulant slot_counts
    slot_counts = {
        "2025-05-14-09": 1,
        "2025-05-14-15": 1,
        "2025-05-15-14": 1,
        "2025-05-15-16": 1,
        "2025-05-16-10": 1
    }

    print("\n[TEST] Vérification des comparaisons pour chaque créneau:")
    for slot_key, count in slot_counts.items():
        is_available = count < max_appointments
        is_available_int = int(count) < int(max_appointments)

        print(f"Créneau {slot_key}: {count} < {max_appointments} = {is_available}")
        print(f"Créneau {slot_key} (avec int): int({count}) < int({max_appointments}) = {is_available_int}")

    # Tester manuellement la comparaison avec différents nombres
    print("\n[TEST] Vérification des comparaisons avec différents compteurs:")
    for count in range(0, 4):
        is_available = count < max_appointments
        is_available_int = int(count) < int(max_appointments)

        print(f"{count} < {max_appointments} = {is_available}")
        print(f"int({count}) < int({max_appointments}) = {is_available_int}")

    print("\n=== Fin du test ===")

if __name__ == "__main__":
    test_max_appointments_per_slot()
