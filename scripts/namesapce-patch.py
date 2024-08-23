import os
import sys
import yaml

# Vérifier si le chemin du dossier est spécifié en argument
if len(sys.argv) < 2:
    print("Veuillez spécifier le chemin du dossier en argument.")
    sys.exit(1)

folder_path = sys.argv[1]

# Vérifier si le chemin du dossier est valide
if not os.path.isdir(folder_path):
    print("Le chemin spécifié n'est pas un dossier valide.")
    sys.exit(1)

# Parcourir récursivement tous les fichiers et dossiers dans le dossier
for root, dirs, files in os.walk(folder_path):
    for filename in files:
        if filename.endswith(".yaml") or filename.endswith(".yml"):
            file_path = os.path.join(root, filename)
            
            # Charger le fichier YAML
            with open(file_path, "r") as file:
                data = list(yaml.safe_load_all(file))
            
            # Modifier chaque ressource dans le fichier YAML
            modified = False
            for resource in data:
                if resource and resource.get("kind") == "Namespace":
                    # Ajouter les labels spécifiés
                    resource.setdefault("metadata", {}).setdefault("labels", {}).update({
                        "pod-security.kubernetes.io/enforce": "privileged",
                        "pod-security.kubernetes.io/enforce-version": "latest",
                        "pod-security.kubernetes.io/audit": "privileged",
                        "pod-security.kubernetes.io/warn": "privileged"
                    })
                    modified = True
            
            # Enregistrer les modifications dans le fichier YAML s'il y en a
            if modified:
                with open(file_path, "w") as file:
                    yaml.dump_all(data, file)
                
                # Imprimer le nom du fichier traité
                print("Fichier traité :", file_path)
