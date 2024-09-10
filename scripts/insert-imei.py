import sys
import yaml
import subprocess
import time

def apply_manifest_and_get_logs(action, imei=None):
    if action == "add":
        sql_command = f"""
        INSERT IGNORE INTO AuthenticationSubscription (ueid, authenticationMethod, encPermanentKey, protectionParameterId, sequenceNumber, authenticationManagementField, algorithmId, encOpcKey, encTopcKey, vectorGenerationInHss, n5gcAuthMethod, rgAuthenticationInd, supi) 
        VALUES (${{UEID}}, '5G_AKA', 'fec86ba6eb707ed08905757b1bb44b8f', 'fec86ba6eb707ed08905757b1bb44b8f', '{{"sqn": "000000000020", "sqnScheme": "NON_TIME_BASED", "lastIndexes": {{"ausf": 0}}}}', '8000', 'c42449363bbad02b66d16bc975d77cc1', NULL, NULL, NULL, NULL, NULL, ${{UEID}});
        SELECT ueid FROM AuthenticationSubscription WHERE ueid = ${{UEID}};
        """
    elif action == "list":
        sql_command = "SELECT ueid FROM AuthenticationSubscription;"
    elif action == "delete":
        sql_command = f"DELETE FROM AuthenticationSubscription WHERE ueid = ${{UEID}}; SELECT ROW_COUNT() as deleted_rows;"
    else:
        raise ValueError("Action must be 'add', 'list', or 'delete'")

    job_name = f"authentication-subscription-job-{action}-{int(time.time())}"
    
    manifest = f"""
apiVersion: batch/v1
kind: Job
metadata:
  name: {job_name}
  namespace: oai-core
spec:
  ttlSecondsAfterFinished: 10
  template:
    spec:
      containers:
      - name: auth-subscription-check
        image: "bitnami/mysql"
        command: ["sh", "-c"]
        env:
        - name: UEID
          value: "{imei if imei else ''}"
        - name: DB_HOST
          value: "mysql"
        - name: MYSQL_PASSWORD
          valueFrom:
            secretKeyRef:
              name: mysql
              key: mysql-password
        - name: MYSQL_USER
          value: "test"
        - name: MYSQL_DATABASE
          value: "oai_db"
        args:
        - |
          mysql -h ${{DB_HOST}} -u ${{MYSQL_USER}} -p${{MYSQL_PASSWORD}} ${{MYSQL_DATABASE}} -e "{sql_command}"
      restartPolicy: Never
  backoffLimit: 4
    """

    # Charger le YAML
    yaml_data = yaml.safe_load(manifest)

    # Écrire le YAML dans un fichier temporaire
    with open('temp_manifest.yaml', 'w') as f:
        yaml.dump(yaml_data, f)

    # Appliquer le manifeste avec kubectl
    try:
        subprocess.run(["kubectl", "apply", "-f", "temp_manifest.yaml"], check=True)
        print(f"Manifeste appliqué avec succès pour l'action: {action}")
        
        # Attendre que le job soit terminé
        print("Attente de la fin du job...")
        while True:
            result = subprocess.run(["kubectl", "get", "job", job_name, "-n", "oai-core", "-o", "jsonpath='{.status.succeeded}'"], capture_output=True, text=True)
            if result.stdout.strip() == "'1'":
                break
            time.sleep(2)
        
        # Récupérer le nom du pod
        pod_name = subprocess.run(["kubectl", "get", "pods", "--selector=job-name=" + job_name, "-n", "oai-core", "-o", "jsonpath='{.items[0].metadata.name}'"], capture_output=True, text=True).stdout.strip()[1:-1]
        
        # Récupérer les logs du pod
        logs = subprocess.run(["kubectl", "logs", pod_name, "-n", "oai-core"], capture_output=True, text=True).stdout
        
        print("\nLogs du job:")
        print(logs)
        
    except subprocess.CalledProcessError as e:
        print(f"Erreur {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2 or len(sys.argv) > 3:
        print("Usage: python script.py <add|list|delete> [IMEI]")
        sys.exit(1)

    action = sys.argv[1]
    if action not in ["add", "list", "delete"]:
        print("Le premier argument doit être 'add', 'list', ou 'delete'")
        sys.exit(1)

    imei = sys.argv[2] if len(sys.argv) == 3 and action in ["add", "delete"] else None

    if action in ["add", "delete"] and not imei:
        print(f"L'IMEI est requis pour l'action '{action}'")
        sys.exit(1)

    apply_manifest_and_get_logs(action, imei)
