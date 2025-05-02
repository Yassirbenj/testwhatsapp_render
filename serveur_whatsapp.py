'''solution de bot dynamique'''

from flask import Flask, request
import requests
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials

app = Flask(__name__)


# 👉 details de connexion :
ACCESS_TOKEN = 'EAAQ3W3MXNZAEBO8ZBx8xcJG6jhk2ZAVd3D4YvhlcyZAgnyJi1CBImLZCPFhYCQkoG17sldKJM9yIojnqQenuUZCqdM1R2NvBdh4au8aZAyLuQOybwcAGlZAUMlgVRYR7r8QZC1RwoC3ZC6xtwJIaZCbvnh11yrURi2SaomAyHshrdIijAAYnUGLmaAd6x8bt10aaJJcLaRHG4jVrMPEs9sipbOU3rPmWYMjJcJRpkYc'
PHONE_NUMBER_ID = '240823895779283'
VERIFY_TOKEN = 'Gabes2025'  # Ce que tu veux, mais cohérent avec ta config Facebook
CREDENTIALS_FILE="whatsappbotleads-5eef4888f75c.json"

# connexion google sheet
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
client = gspread.authorize(creds)
sheet = client.open("leads whatsapp").sheet1  # Mets ici le nom exact de ton Google Sheet


# Charger le scénario depuis le fichier process.json
with open('process.json', 'r') as f:
    process = json.load(f)


# Stocker l'état et les réponses de chaque utilisateur
user_data = {}

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
                        text = message.get('text', {}).get('body')
                        sender = message['from']

                        if sender not in user_data:
                            user_data[sender] = {
                                'current_step': 0,
                                'data': {}
                            }
                            send_step_message(sender, 0)
                            return "OK", 200

                        step_index = user_data[sender]['current_step']
                        current_step = process[step_index]

                        # === SAUVEGARDE de la réponse utilisateur ===
                        save_key = current_step.get('save_as')
                        if save_key:
                            user_data[sender]['data'][save_key] = text

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

                        if user_data[sender]['current_step'] == 99:
                            send_message(sender, "Merci beaucoup, nous vous contacterons bientôt ! 👋")
                            print(f"✅ Données finales utilisateur {sender} :", user_data[sender]['data'])

                            # Construction de la ligne à enregistrer
                            record = [sender]  # Numéro de téléphone WhatsApp
                            for key, value in user_data[sender]['data'].items():
                                record.append(value)

                            # Ajouter une ligne dans Google Sheets
                            sheet.append_row(record)

                            print(f"✅ Lead ajouté dans Google Sheet : {record}")

                        else:
                            send_step_message(sender, user_data[sender]['current_step'])

        return "OK", 200

# === ENVOI DE MESSAGES WHATSAPP ===

def send_step_message(to_number, step_index):
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
    response = requests.post(url, headers=headers, data=json.dumps(payload))
    print("Réponse envoi message:", response.status_code, response.json())


# === RUN APP ===
if __name__ == '__main__':
    app.run(port=5000)
