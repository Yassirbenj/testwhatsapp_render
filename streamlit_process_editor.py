import streamlit as st
import json
import os

# Charger le process existant
if os.path.exists('process.json'):
    with open('process.json', 'r') as f:
        process = json.load(f)
else:
    process = []

st.title("Créateur de Scénario WhatsApp Bot 🚀")

# Partie 1 : demander le nombre d'étapes
if 'num_steps' not in st.session_state:
    st.subheader("Définir le nombre d'étapes du scénario")

    num_steps_input = st.number_input("Combien d'étapes veux-tu créer ?", min_value=1, step=1, key="input_num_steps")

    if st.button("Valider le nombre d'étapes"):
        st.session_state.num_steps = num_steps_input
        st.session_state.current_step = 0
        st.rerun()  # Redémarrer Streamlit pour prendre en compte
    st.stop()

# Partie 2 : saisie du process
if st.session_state.current_step < st.session_state.num_steps:

    step_idx = st.session_state.current_step

    st.subheader(f"➡️ Saisie de l'étape {step_idx + 1}")

    message = st.text_area("Texte du message à envoyer (inclure directement les options dans le texte)", key=f"message_{step_idx}")

    expected_type = st.selectbox("Type de réponse attendue", ["Choix multiple", "Texte libre"], key=f"type_{step_idx}")

    expected_answers = []
    next_step = {}

    if expected_type == "Choix multiple":
        number_of_choices = st.number_input(f"Nombre d'options pour cette étape", min_value=1, max_value=5, step=1, key=f"nb_choices_{step_idx}")

        for i in range(number_of_choices):
            choice_value = st.text_input(f"Valeur attendue pour l'option {i+1} (ex: 1 ou 2)", key=f"choice_{step_idx}_{i}")

            step_options = list(range(st.session_state.num_steps)) + [99]
            selected_next_step = st.selectbox(f"Étape suivante après réponse '{choice_value}'", step_options, key=f"next_{step_idx}_{i}")

            expected_answers.append(choice_value.strip())
            next_step[choice_value.strip()] = selected_next_step

    elif expected_type == "Texte libre":
        expected_answers = "free_text"
        step_options = list(range(st.session_state.num_steps)) + [99]
        selected_next_step = st.selectbox("Étape suivante après réponse libre", step_options, key=f"next_free_{step_idx}")
        next_step = selected_next_step

    save_as = st.text_input("Nom de la variable à sauvegarder (ex: Nom, Téléphone, Formation)")

    if st.button("✅ Valider cette étape", key=f"validate_{step_idx}"):

        new_step = {
            "message": message,
            "expected_answers": expected_answers,
            "next_step": next_step
        }
        if save_as:
            new_step['save_as'] = save_as.strip()

        process.append(new_step)

        with open('process.json', 'w') as f:
            json.dump(process, f, indent=2)

        st.success(f"Étape {step_idx+1} ajoutée avec succès !")

        st.session_state.current_step += 1
        st.rerun()

else:
    st.success("✅ Toutes les étapes ont été créées !")
    st.subheader("Scénario actuel :")
    for idx, step in enumerate(process):
        st.markdown(f"**Étape {idx}**")
        st.json(step)

    if st.button("🔄 Réinitialiser pour tout recommencer"):
        st.session_state.clear()
        process.clear()
        with open('process.json', 'w') as f:
            json.dump([], f)
        st.rerun()
