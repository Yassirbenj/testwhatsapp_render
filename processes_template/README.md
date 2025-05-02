# Templates de Processus WhatsApp

Ce dossier contient des exemples de processus pour le bot WhatsApp. Ces templates servent de base pour créer de nouveaux processus.

## Structure des fichiers

Chaque fichier JSON de processus contient :

```json
{
    "name": "Nom du processus",
    "created_at": "Horodatage",
    "steps": [
        {
            "message": "Message à envoyer",
            "expected_answers": "Type de réponse attendue",
            "next_step": "Prochaine étape",
            "save_as": "Clé de sauvegarde"
        }
    ]
}
```

## Types de réponses attendues

- `"free_text"` : Texte libre
- `"no_reply"` : Pas de réponse attendue
- `["1", "2", "3"]` : Choix multiples

## Prochaine étape

- Numéro simple : `"next_step": 2`
- Choix conditionnel :
```json
"next_step": {
    "1": 3,
    "2": 4,
    "3": 5
}
```

## Templates disponibles

1. `garage_example.json` : Processus pour la prise de rendez-vous au garage
   - Collecte des informations client
   - Choix du type de service
   - Questions spécifiques selon le service
   - Prise de rendez-vous

2. `formation_example.json` : Processus pour les demandes de formation
   - Collecte des informations candidat
   - Choix du type de formation
   - Questions spécifiques selon le type
   - Collecte des coordonnées

## Utilisation

1. Copier le template souhaité
2. Modifier les messages et la logique selon vos besoins
3. Sauvegarder dans le dossier `processes/`
4. Activer le processus via l'interface web

## Bonnes pratiques

1. Toujours tester le processus avant de l'activer
2. Vérifier la cohérence des numéros d'étape
3. Utiliser des clés de sauvegarde explicites
4. Ajouter des messages d'aide si nécessaire
5. Gérer les cas d'erreur
