#!/bin/bash


package=$1
repo=$2

results=$(kubectl get packagerevision -o=json | jq '.items[] | select((.spec.packageName | startswith("'"$package"'")) and .spec.repository == "'"$repo"'") | [.metadata.name] | @tsv')

IFS=$'\n' read -rd '' -a result_array <<< "$results"


command_prop="kpt alpha rpkg propose-delete ${result_array[*]} -n default"

# Exécute la commande
eval "$command_prop"


command_del="kpt alpha rpkg delete ${result_array[*]} -n default"

eval "$command_del"
