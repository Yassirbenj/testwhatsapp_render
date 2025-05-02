from flask import Flask, request
import requests
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials

app = Flask(__name__)


# 👉 Remplace par tes propres informations :
ACCESS_TOKEN = 'EAAQ3W3MXNZAEBOZCAjLWXPZAGmix5rj91dGZBzwyK9NSei8YceznBLEVc2Wge8Wwss93iOfhZCFTLq963oTMdzxe80SahKYZCNZB0HyZBJj5nEXrd5Vf1xZBmjwMcUv5dUZBjEjahsJ90Wdv2ZCmFRUJnSOW3Aql80L2hixHqx7bN3MbK9Q8Fmn8uLZC5yMdYEBVZCZASH67ghTysULyrgbkwOXZBAYhGR6GU4puNVtZAutTnuIZD'
PHONE_NUMBER_ID = '240823895779283'
VERIFY_TOKEN = 'Gabes2025'  # Ce que tu veux, mais cohérent avec ta config Facebook
CREDENTIALS_FILE="whatsappbotleads-5eef4888f75c.json"

# Connecte-toi à Google Sheets
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
client = gspread.authorize(creds)
sheet = client.open("leads whatsapp").sheet1  # Mets ici le nom exact de ton Google Sheet

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
        print("Données reçues:", json.dumps(data, indent=2))

        if data.get('entry'):
            for entry in data['entry']:
                for change in entry['changes']:
                    value = change.get('value')
                    messages = value.get('messages')
                    if messages:
                        message = messages[0]
                        text = message.get('text', {}).get('body')
                        sender = message['from']

                        print(f"Message reçu de {sender}: {text}")
                        print("État utilisateur actuel :", user_data.get(sender))

                        # Initialise la fiche utilisateur si elle n'existe pas
                        if sender not in user_data:
                            user_data[sender] = {
                                'state': 'initial',
                                'name': '',
                                'phone': '',
                                'formation': ''
                            }

                        state = user_data[sender]['state']

                        # LOGIQUE D'ÉCHANGE
                        if state == 'initial':
                            if text.lower() == "1":
                                send_question_with_choices(sender)
                                user_data[sender]['state'] = 'awaiting_first_response'

                        elif state == 'awaiting_first_response':
                            if text == "1":
                                send_training_choices(sender)
                                user_data[sender]['state'] = 'awaiting_training_choice'
                            elif text == "2":
                                send_sorry_message(sender)
                                user_data[sender]['state'] = 'completed'

                        elif state == 'awaiting_training_choice':
                            if text in ["1", "2", "3"]:
                                if text == "1":
                                    user_data[sender]['formation'] = "Informatique"
                                elif text == "2":
                                    user_data[sender]['formation'] = "Management"
                                elif text == "3":
                                    user_data[sender]['formation'] = "Arts Visuels"

                                send_message(sender, "Merci, notre responsable pédagogique va te contacter. Peux-tu me confirmer ton nom et prénom ?")
                                user_data[sender]['state'] = 'awaiting_name'

                        elif state == 'awaiting_name':
                            user_data[sender]['name'] = text
                            send_message(sender, "Merci ! Quel est ton numéro de téléphone ?")
                            user_data[sender]['state'] = 'awaiting_phone'

                        elif state == 'awaiting_phone':
                            user_data[sender]['phone'] = text
                            send_message(sender, "Merci et à bientôt ! 👋")
                            user_data[sender]['state'] = 'completed'

                            # AJOUTER DANS GOOGLE SHEETS
                            row = [
                                sender,
                                user_data[sender]['name'],
                                user_data[sender]['phone'],
                                user_data[sender]['formation']
                            ]
                            sheet.append_row(row)
                            print(f"✅ Lead ajouté dans Google Sheet : {row}")

    return "OK", 200

# === ENVOI DE MESSAGES WHATSAPP ===

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

def send_question_with_choices(to_number):
    message = (
        "Merci de nous consacrer ces quelques minutes. Es tu intéressé par nos cursus post bac ou de masters ?\n\n"
        "1️⃣ Post bac\n"
        "2️⃣ Masters"
    )
    send_message(to_number, message)

def send_training_choices(to_number):
    message = (
        "Merci, quelle formation t'intéresse ?\n\n"
        "1️⃣ Informatique\n"
        "2️⃣ Management\n"
        "3️⃣ Arts Visuels"
    )
    send_message(to_number, message)

def send_sorry_message(to_number):
    message = "Désolé, quelqu'un a dû renseigner le formulaire par erreur. Je vous souhaite une bonne journée ☀️."
    send_message(to_number, message)

# === RUN APP ===
if __name__ == '__main__':
    app.run(port=5000)
