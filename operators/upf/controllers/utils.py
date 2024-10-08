################################################################################
# Licensed to the OpenAirInterface (OAI) Software Alliance under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The OpenAirInterface Software Alliance licenses this file to You under
# the terms found in the LICENSE file in the root of this source tree.
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#-------------------------------------------------------------------------------
# For more information about the OpenAirInterface (OAI) Software Alliance:
#      contact@openairinterface.org
##################################################################################

import os
import yaml
import kubernetes
from kubernetes.client.rest import ApiException
from datetime import datetime
from dateutil.tz import tzutc
import json
import requests

requests.packages.urllib3.disable_warnings() 

TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
KUBERNETES_TYPE=str(os.getenv('KUBERNETES_TYPE','vanilla')).lower()    ##Allowed values VANILLA/Openshift
if KUBERNETES_TYPE not in ['vanilla','openshift']:
    print('Allowed values for kubernetes type are vanilla/openshift')
TOKEN=os.popen('cat /var/run/secrets/kubernetes.io/serviceaccount/token').read() ## Token used to communicate with Kube cluster
NF_TYPE=str(os.getenv('NF_TYPE','upf'))      ## Network function name
LABEL={'workload.nephio.org/oai': f"{NF_TYPE}"}   ## Labels to put inside the owned resources
OP_CONF_PATH=str(os.getenv('OP_CONF_PATH',f"/tmp/op/{NF_TYPE}.yaml"))  ## Operators configuration file
NF_CONF_PATH = str(os.getenv('NF_CONF_PATH',f"/tmp/nf/{NF_TYPE}.yaml"))  ## Network function configuration file
DEPLOYMENT_FETCH_INTERVAL=int(os.getenv('DEPLOYMENT_FETCH_INTERVAL',1)) # Fetch the status of deployment every x seconds
DEPLOYMENT_FETCH_ITERATIONS=int(os.getenv('DEPLOYMENT_FETCH_ITERATIONS',100))  # Number of times to fetch the deployment
LOG_LEVEL = str(os.getenv('LOG_LEVEL','INFO'))    ## Log level of the controller
TESTING = str(os.getenv('TESTING','yes'))    ## If testing the network function, it will remove the init container which checks for NRFs availability
HTTPS_VERIFY = bool(os.getenv('HTTPS_VERIFY',False)) ## To verfiy HTTPs certificates when communicating with cluster
TOKEN=os.popen('cat /var/run/secrets/kubernetes.io/serviceaccount/token').read() ## Token used to communicate with Kube cluster
KUBERNETES_BASE_URL = str(os.getenv('KUBERNETES_BASE_URL','http://127.0.0.1:8080'))
LOADBALANCER_IP = str(os.getenv('LOADBALANCER_IP',None))
SVC_TYPE = str(os.getenv('SVC_TYPE','ClusterIP')) 

if SVC_TYPE not in ['ClusterIP', 'LoadBalancer', 'NodePort']:
    print(f"SVC_TYPE is case sensitive are you spelling {SVC_TYPE} correct?")
    sys.exit('-1')

def create_deployment(name: str=None, 
                    namespace: str=None, 
                    compute: dict=None, 
                    labels: dict=None, 
                    image: str=None,
                    image_pull_secrets: list=None, 
                    ports: list=None,
                    nrf_svc:str=None,
                    interfaces: list=None,
                    dnn_subnets: list=None,
                    config_map: str=None, 
                    nf_type: str=None, 
                    sa_name: str=None,
                    nad:dict=None,
                    logger=None,
                    kopf=None):
    '''
    :param name: name of the crd object
    :type name: str
    :param namespace: Namespace name
    :type namespace: str
    :param nrf_svc: NRF svc
    :type nrf_svc: str
    :param compute: compute resource req and limit
    :type compute: dict
    :param labels: labels
    :type labels: dict
    :param image: image name
    :type image: str
    :param image_pull_secrets: image_pull_secrets name
    :type image_pull_secrets: list
    :param ports: list of ports
    :type ports: list
    :param interfaces: list of interfaces to attach with this NF
    :type interfaces: list
    :param dnn_subnets: list of DNNs subnets
    :type dnn_subnets: list
    :param config_map: config_map name
    :type config_map: str
    :param nf_type: nf_type name
    :type nf_type: str
    :param sa_name: sa_name name
    :type sa_name: str
    :param logger: logger
    :type logger: <class 'kopf._core.actions.loggers.ObjectLogger'>
    :param nad: network attachement defination
    :type nad: dict
    :param kopf: Instance of kopf
    :return: deployment
    :rtype: dict
    '''
    _ports = []
    _interfaces = []
    error=False
    for port in ports:
        _ports.append(
            {
                'name':port['name'],
                'containerPort':int(port['port']),
                'protocol':port['protocol']
            }
            )
    if nrf_svc is None:
        nrf_svc = "oai-nrf" #default value
    URL = f"curl --connect-timeout 1 --head -X GET http://{nrf_svc}/nnrf-nfm/v1/nf-instances?nf-type='NRF' --http2-prior-knowledge"

    forward_subnets_n6 = " && ".join([f"iptables -t nat -A POSTROUTING -s {subnet} -o n6 -j MASQUERADE" for subnet in dnn_subnets])
    logger.info(f"{dnn_subnets}")
    deployment = {
                  "apiVersion": "apps/v1",
                  "kind": "Deployment",
                  "metadata": {
                    "name": name,
                    "namespace": namespace,
                    "labels": labels
                  },
                  "spec": {
                    "replicas": 1,
                    "selector": {
                      "matchLabels": labels
                    },
                    "strategy": {
                      "type": "Recreate"
                    },
                    "template": {
                      "metadata": {
                        "labels": labels 
                        },
                      "spec": {
                        "securityContext": {
                          "runAsGroup": 0,
                          "runAsUser": 0
                        },
                        "imagePullSecrets":image_pull_secrets,
                        "initContainers": [{
                            "name": 'init',
                            "image": "docker.io/alpine/curl:3.14",
                            "imagePullPolicy": "IfNotPresent",
                            "command": [
                            'sh', 
                            '-c', 
                            f"until {URL}; do echo waiting for nrf svc {nrf_svc} to respond; sleep 1; done"
                            ]
                        }],
                        "containers": [
                          {
                            "name": name,
                            "image": image,
                            "imagePullPolicy": "IfNotPresent",
                            "securityContext": {
                                "privileged": True
                            },
                            "resources": {
                                "requests": {
                                "memory": compute['req']['memory'],
                                "cpu": compute['req']['cpu']
                                },
                                "limits": {
                                "memory": compute['limits']['memory'],
                                "cpu": compute['limits']['cpu']
                                }
                            },
                            "volumeMounts": [
                              {
                                "mountPath": f"/openair-{nf_type}/etc",
                                "name": "configuration"
                              }],
                            "ports": _ports,
                            "command": [
                                        "/bin/sh",
                                        "-c"
                                        ],
                                        "args" : [
                                        f"sysctl -w net.ipv4.ip_forward=1 {'&& ' + forward_subnets_n6 if forward_subnets_n6 else ''}&& /openair-{nf_type}/bin/oai_{nf_type} -c /openair-{nf_type}/etc/{nf_type}.yaml -o"
                                        ]
                          }
                        ],
                        "volumes": [
                          {
                            "configMap": {
                              "name": config_map
                            },
                            "name": "configuration"
                          }
                        ],
                        "dnsPolicy": "ClusterFirst",
                        "restartPolicy": "Always",
                        "serviceAccountName": sa_name,
                        "terminationGracePeriodSeconds": 5
                      }
                    }
                  }
                }

    if interfaces is not None:
        for interface in interfaces:
            nad_name=f"{name}-{interface['name']}"
            nad_status = create_nad(
                                name=nad_name,
                                namespace=namespace,
                                nad_config=nad,
                                labels=labels,
                                logger=logger,
                                kopf=kopf,
                                nf_type=nf_type)
            if nad_status['status']:
                _interfaces.append({'name':nad_status['name'],
                                    'interface':interface['name'],
                                    'ips':[interface['ipv4']['address']],
                                    'gateway':[interface['ipv4']['gateway']]
                                    })
            else:
                output = {'message': 'Deployment failure',
                          'reason': nad_status['reason'],
                          'status': "False",
                          'type': "Error",
                          'generation': 0,
                          'observedGeneration': 0,
                          'ready': False,
                          'error': True
                          }
                logger.error(f"Error {nad_status['reason']}, in creating deployment {name} in namespace {namespace}" )
                return output
        deployment['spec']['template']['metadata'].update(
                                        {'annotations':
                                            {'k8s.v1.cni.cncf.io/networks': json.dumps(_interfaces)}})
    if TESTING == 'yes':
        deployment['spec']['template']['spec'].pop('initContainers')
    kopf.adopt(deployment)  # includes namespace, name, existing labels
    kopf.label(deployment, labels, nested=['spec.template'])
    creation_timestamp = None
    available_replicas = None
    last_transition_time = datetime.now().strftime(TIME_FORMAT) 
    message = f"{name} pod(s) is(are) creating"
    reason = "MinimumReplicasNotAvailable"
    _type = "Progressing"
    generation = 0
    ready = False
    observed_generation = 0
    _status = "False"
    try:
        api = kubernetes.client.AppsV1Api()
        obj = api.create_namespaced_deployment(
                namespace=namespace,
                body=deployment
            ).to_dict()
        status = obj['status']
        creation_timestamp = obj['metadata']['creation_timestamp']
        available_replicas = status['available_replicas']        
        if 'generation' in obj['metadata'].keys():
            generation = obj['metadata']['generation']
        observed_generation = status['observed_generation']
        if status['conditions'] is not None and len(status['conditions'])>0:
            last_transition_time = status['conditions'][0]['last_transition_time']
            message = status['conditions'][0]['message']
            reason = status['conditions'][0]['reason']
            _status = status['conditions'][0]['status']
            ready = status['ready_replicas'] is not None and int(status['ready_replicas'])
            _type = status['conditions'][0]['type']
    except ApiException as e:
        logger.error(f"Exception with reason {e.reason}, code {e.status} in creating deployment {name} in namespace {namespace}" )
        raise kopf.PermanentError(f"Can not create Deployment {name} in namespace {namespace} reason {e.reason}")


    output = {'last_transition_time': last_transition_time,
              'message': message,
              'reason': reason,
              'status': _status,
              'type': "Progressing",
              'generation': generation,
              'observedGeneration': observed_generation,
              'ready': ready,
              'creation_timestamp': creation_timestamp,
              'error': error
              }
    return output


def create_sa(name:str=None, namespace: str=None, labels:dict=None, logger=None,kopf=None ):
    '''
    :param name: name of the service account
    :type name: str
    :param namespace: Namespace name
    :type namespace: str
    :param labels: labels
    :type labels: dict
    :param logger: logger
    :type logger: <class 'kopf._core.actions.loggers.ObjectLogger'>
    :param kopf: Instance of kopf
    :return: status
    :rtype: dict
    '''
    sa   =  {
              "apiVersion": "v1",
              "kind": "ServiceAccount",
              "metadata": {
                "name": name,
                "namespace":namespace
              }
            }
    kopf.adopt(sa)  # includes namespace, name, existing labels
    kopf.label(sa, labels, nested=['spec.template'])
    creation_timestamp =  None
    try:
        api = kubernetes.client.CoreV1Api()
        obj = api.create_namespaced_service_account(
                namespace=namespace,
                body=sa
            ).to_dict()
        creation_time =  obj['metadata']['creation_timestamp']
        name = obj['metadata']['name']
    except ApiException as e:
        logger.error(f"Exception with reason {e.reason}, code {e.status} in creating service account {name} in namespace {namespace}")
        raise kopf.PermanentError(f"Can not create service account {name} in namespace {namespace} reason {e.reason}")

    return {'creation_timestamp':creation_timestamp,'name':name}

def create_config_map(name: str=None, namespace: str=None, 
                     labels:dict=None, configuration:dict=None, 
                     logger=None, kopf=None, nf_type: str=None):
    '''
    :param name: name of the configmap
    :type name: str
    :param namespace: Namespace name
    :type namespace: str
    :param labels: labels
    :type labels: dict
    :param config: configuration 
    :type config: dict
    :param logger: logger
    :type logger: <class 'kopf._core.actions.loggers.ObjectLogger'>
    :param kopf: Instance of kopf
    :return: status
    :rtype: dict
    ''' 

    metadata = kubernetes.client.V1ObjectMeta(
        name=name,
        namespace=namespace,
    )

    configmap = kubernetes.client.V1ConfigMap(
        api_version="v1",
        kind="ConfigMap",
        data={f"{nf_type}.yaml":configuration},
        metadata=metadata
    )
    kopf.adopt(configmap)  # includes namespace, name, existing labels
    kopf.label(configmap, labels, nested=['spec.template'])

    creation_timestamp =  None
    try:
        api = kubernetes.client.CoreV1Api()
        obj = api.create_namespaced_config_map(
                namespace=namespace,
                body=configmap
            ).to_dict()
        creation_time =  obj['metadata']['creation_timestamp']
        name = obj['metadata']['name']
    except ApiException as e:
        logger.error(f"Exception with reason {e.reason}, code {e.status} in creating configmap {name} in namespace {namespace}")
        raise kopf.PermanentError(f"Can not create configmap {name} in namespace {namespace} reason {e.reason}")
        return {}

    return {'creation_timestamp':creation_timestamp,'name':name}


def deployment_status(deployment_name: str=None, namespace: str=None,logger=None, kopf=None):
    '''
    :param deployment_name: name of the deployment
    :type deployment_name: str
    :param namespace: Namespace name
    :type namespace: str
    :param logger: logger
    :type logger: <class 'kopf._core.actions.loggers.ObjectLogger'>
    :param kopf: Instance of kopf
    :return: status
    :rtype: dict
    ''' 
    try:
        api = kubernetes.client.AppsV1Api()
        response = api.read_namespaced_deployment_status(name=deployment_name,namespace=namespace).to_dict()
        status = response['status']
    except ApiException as e:
        logger.error(f"Exception with reason {e.reason}, code {e.status} in reading the status of deployment {deployment_name} in namespace {namespace}" )
        raise kopf.PermanentError(f"Exception with reason {e.reason}, code {e.status} in reading the status of deployment {deployment_name} in namespace {namespace}")

    creation_timestamp = response['metadata']['creation_timestamp']
    available_replicas = status['available_replicas']
    last_transition_time = datetime.now().strftime(TIME_FORMAT) 
    message = f"{deployment_name} pod(s) is(are) creating"
    reason = "MinimumReplicasNotAvailable"
    _type = "Progressing"
    generation = 0
    ready = False
    observed_generation = 0
    _status = "False"
    if 'generation' in response['metadata'].keys():
        generation = response['metadata']['generation']

    conditions = [
                  {'lastTransitionTime': last_transition_time,
                  'message': message,
                  'reason': reason,
                  '_status': _status,
                  'type': "Progressing",
                  'observedGeneration': generation,
                  }
                ]

    if status['conditions'] is not None and len(status['conditions'])>0:
        ready = status['ready_replicas'] is not None and int(status['ready_replicas'])
        observed_generation = status['observed_generation']
        conditions = []
        for c in status['conditions']:
            conditions.append({
                                'lastTransitionTime':datetime.now().strftime(TIME_FORMAT),
                                'message':c['message'],
                                'reason':c['reason'],
                                'status':c['status'],
                                'type': c['type'],
                                'observedGeneration':generation
                                })
    output = {'conditions':conditions,
              'observedGeneration': observed_generation,
              'ready': ready
              }

    return output

def create_svc(name: str=None, 
               namespace: str=None, 
               labels: dict=None, 
               ports: list=None,
               logger=None,
               kopf=None
            ):
    '''
    :param name: name of the configmap
    :type name: str
    :param namespace: Namespace name
    :type namespace: str
    :param labels: labels
    :type labels: dict
    :param ports: ports 
    :type config: dict
    :param logger: logger
    :type logger: <class 'kopf._core.actions.loggers.ObjectLogger'>
    :param kopf: Instance of kopf
    :return: status
    :rtype: dict
    ''' 

    _ports = []
    for port in ports:
        _ports.append(
            {
                'name':port['name'],
                'port':int(port['port']),
                'protocol':port['protocol'],
                'targetPort': int(port['port'])
            }
            )

    # SVC_TYPE (LoadBalancer,ClusterIP,NodePort)
    svc = {
          "apiVersion": "v1",
          "kind": "Service",
          "metadata": {
            "name": name,
            "labels": labels
          },
          "spec": {
            "type": SVC_TYPE,
            "clusterIP": "None",
            "ports": _ports,
            "selector": labels
          }
        }
    if LOADBALANCER_IP is not None:
        svc['spec'].update({'loadBalancerIP':LOADBALANCER_IP})
    if SVC_TYPE in ['LoadBalancer','NodePort']:
        svc['spec'].pop('clusterIP')

    kopf.adopt(svc)  # includes namespace, name, existing labels
    kopf.label(svc, labels, nested=['spec.template'])
    logger.info(f"Service: {svc}") #logger 
    creation_timestamp =  None
    try:
        api = kubernetes.client.CoreV1Api()
        obj = api.create_namespaced_service(
                namespace=namespace,
                body=svc
            ).to_dict()
        creation_time =  obj['metadata']['creation_timestamp']
        name = obj['metadata']['name']
    except ApiException as e:
        logger.error(f"Exception with reason {e.reason}, code {e.status} in creating service {name} in namespace {namespace}")
        raise kopf.PermanentError(f"Can not create service {name} in namespace {namespace} reason {e.reason}")

    return {'creation_timestamp':creation_timestamp,'name':name}

def create_nad(name: str=None, namespace: str=None, 
              labels:dict=None, 
              nad_config:dict=None, 
              logger=None, kopf=None, nf_type: str=None):
    '''
    :param name: name of the configmap
    :type name: str
    :param namespace: Namespace name
    :type namespace: str
    :param labels: labels
    :type labels: dict
    :param config: configuration 
    :type config: dict
    :param logger: logger
    :type logger: <class 'kopf._core.actions.loggers.ObjectLogger'>
    :param kopf: Instance of kopf
    :return: status
    :rtype: Boolean
    '''
    headers = {"Content-type": "application/json",
        "Accept": "application/json",
        "Authorization": "Bearer {}".format(TOKEN)}
    try:
        r = requests.get(f"{KUBERNETES_BASE_URL}/apis/k8s.cni.cncf.io/v1/namespaces/{namespace}/network-attachment-definitions/{name}", headers=headers, verify=HTTPS_VERIFY)
    except Exception as e:
        return {'status' :False,'reason':'NotAbleToCommunicateWithTheCluster'}
    if r.status_code in [200]:
        Response = {'status': True,'name':name}
    elif r.status_code in [401,403]:
        Response = {'status' :False,'reason':'Unauthorized'}
    elif r.status_code == 404:
        Response = {'status':False,'reason':f"NetworkAttachmentDefinitionDoesNotExist"}
    elif r.status_code == 404 and nad_config['create']:
        config = {
                      "cniVersion": "0.3.1",
                      "plugins": [
                        {
                          "type": "macvlan",
                          "capabilities": { "ips": True },
                          "master": f"{nad_config['parent']}",
                          "mode": "bridge",
                          "ipam": {
                            "type": "static"
                          }
                        }, {
                          "capabilities": { "mac": True },
                          "type": "tuning"
                        }
                    ]
                    }

        if 'routes' in nad_config.keys():
            config['plugins'][0]['ipam'].update({"routes":nad_config['routes']})

        nad = {
                    "apiVersion": "k8s.cni.cncf.io/v1",
                    "kind": "NetworkAttachmentDefinition",
                    "metadata": {
                        "name": name,
                        "namespace": namespace,
                        "labels": labels
                    },
                    "spec": {
                        "config":str(json.dumps(config))
                        }
                 }
        logger.debug(f"network-attachment-definition {name} does not exist in namespace {namespace} operator is creating it now")
        r = requests.post(f"{KUBERNETES_BASE_URL}/apis/k8s.cni.cncf.io/v1/namespaces/{namespace}/network-attachment-definitions", headers=headers, json=nad, verify=HTTPS_VERIFY)
        logger.debug("Response of the request to create nad %s response %s" %(r.request.url, r.json()))                   
        if r.status_code in [200,201]:
            Response = {'status': True,'name':name}
        elif r.status_code in [401,403]:
            Response = {'status' :False,'reason':'unauthorized'}
        elif r.status_code == 404:
            Response ={'status': False,'reason':'notFound'}        
        else : 
            Response = {'status':False,'reason':r.json()}
    return Response

def delete_nad(name: str=None, namespace: str=None, 
              logger=None):
    '''
    :param name: name of the configmap
    :type name: str
    :param namespace: Namespace name
    :type namespace: str
    :param logger: logger
    :type logger: <class 'kopf._core.actions.loggers.ObjectLogger'>
    :param kopf: Instance of kopf
    :return: status
    :rtype: Boolean
    '''
    headers = {"Content-type": "application/json",
        "Accept": "application/json",
        "Authorization": "Bearer {}".format(TOKEN)}
    r = requests.delete(f"{KUBERNETES_BASE_URL}/apis/k8s.cni.cncf.io/v1/namespaces/{namespace}/network-attachment-definitions/{name}", headers=headers, verify=HTTPS_VERIFY)
    logger.debug("Response of the request to delete nad %s response %s" %(r.request.url, r.json()))
    if r.status_code in [200,202,204]:
        Response = {'status': True,'name':name}
    elif r.status_code in [401,403]:
        Response = {'status' :False,'reason':'unauthorized'}
    elif r.status_code == 404:
        Response ={'status': False,'reason':'notFound'}        
    else: 
        Response = {'status':False,'reason':r.json()}

    return Response

def get_param_ref(name: str=None, namespace: str=None,
              logger=None, kind: str=None, apiVersion:str=None):
    '''
    :param name: name of the configmap
    :type name: str
    :param namespace: Namespace name
    :type namespace: str
    :param logger: logger
    :type logger: <class 'kopf._core.actions.loggers.ObjectLogger'>
    :param kind: kind of the parameter ref
    :type kind: string
    :param apiVersion: apiVersion of the parameter ref
    :type apiVersion: string
    :return: Response
    :rtype: dict
    '''
    headers = {"Content-type": "application/json",
        "Accept": "application/json",
        "Authorization": "Bearer {}".format(TOKEN)}
    r = requests.get(f"{KUBERNETES_BASE_URL}/apis/{apiVersion}/namespaces/{namespace}/{kind}s/{name}", headers=headers, verify=HTTPS_VERIFY)
    logger.debug(f"Response of request to fetch {apiVersion} {r.request.url} response {r.json()}")
    if r.status_code==200:
        Response = {'status': True,'output':r.json()}
    elif r.status_code in [401,403]:
        Response = {'status' :False,'reason':'unauthorized'}
    elif r.status_code == 404:
        Response ={'status': False,'reason':'notFound'}
    else:
        Response = {'status':False,'reason':r.json()}

    return Response

def create_role(name: str=None, namespace: str=None, 
              logger=None, 
              labels: dict=None,
              rules: list=None,
              ):
    '''
    :param name: name of the role
    :type name: str
    :param namespace: Namespace name
    :type namespace: str
    :param logger: logger
    :type logger: <class 'kopf._core.actions.loggers.ObjectLogger'>
    :param labels: labels
    :type labels: dict
    :param rules: rules for role
    :type rules: list
    :return: Response (status:created, pending, error, unauthorized)
    :rtype: dict

    ''' 
    body = {
                  "apiVersion": "rbac.authorization.k8s.io/v1",
                  "kind": "Role",
                  "metadata": {
                    "name": str(name).lower(),
                    "labels": labels,
                    "namespace": namespace
                  },
                  "rules": rules
                }

    headers = {"Content-type": "application/json",
        "Accept": "application/json",
        "Authorization": "Bearer {}".format(TOKEN)}
    r=requests.post(f"{KUBERNETES_BASE_URL}/apis/rbac.authorization.k8s.io/v1/namespaces/{namespace}/roles", headers=headers, json=body, verify=HTTPS_VERIFY)
    logger.debug(f"Response of the request {r.request.url} response {r.json()}")
    if r.status_code in [200,201]:
        Response = {'status':True}
    elif r.status_code == 202:
        Response = {'status':False}
    elif r.status_code == 401:
        Response = {'status': False}
    else:
        Response = {'status':False}
    return Response

#get
def get_role(name: str=None, namespace: str=None, logger=None):
    '''
    :param name: name of the role
    :type name: str
    :param namespace: Namespace name
    :type namespace: str
    :param logger: logger
    :type logger: <class 'kopf._core.actions.loggers.ObjectLogger'>
    :return: Response
    :rtype: dict
    '''
    headers = {"Accept": "application/json",
        "Authorization": "Bearer {}".format(TOKEN)}
    r=requests.get(f"{KUBERNETES_BASE_URL}/apis/rbac.authorization.k8s.io/v1/namespaces/{namespace}/roles/{name}", headers=headers, verify=HTTPS_VERIFY)
    logger.debug(f"Response of the request {r.request.url} response {r.json()}")
    if r.status_code in [200,204]:
        Response = {'status':True}
    elif r.status_code == 202:
        Response = {'status':False}
    elif r.status_code == 404:
        Response = {'status': False}
    else:
        Response = {'status':False}
    return Response

#Delete
def delete_role(name: str=None, namespace: str=None, logger=None):
    '''
    :param name: name of the role
    :type name: str
    :param namespace: Namespace name
    :type namespace: str
    :param logger: logger
    :type logger: <class 'kopf._core.actions.loggers.ObjectLogger'>
    :return: Response
    :rtype: dict
    '''
    headers = {"Accept": "application/json",
        "Authorization": "Bearer {}".format(TOKEN)}
    r=requests.delete(f"{KUBERNETES_BASE_URL}/apis/rbac.authorization.k8s.io/v1/namespaces/{namespace}/roles/{name}", headers=headers, verify=HTTPS_VERIFY)
    logger.debug(f"Response of the request {r.request.url} response {r.json()}")
    if r.status_code in [200,204]:
        Response = {'status':True}
    elif r.status_code == 202:
        Response = {'status':False}
    elif r.status_code == 404:
        Response = {'status':False}
    else:
        Response = {'status':False}
    return Response

def create_role_binding(name: str=None, namespace: str=None, 
              sa_name: str=None,
              role_name: str=None,
              logger=None, 
              labels: dict=None
              ):

    '''
    :param name: name of the role
    :type name: str
    :param sa_name: Service Account Name
    :type sa_name: str
    :param role_name: Role Name
    :type role_name: str
    :param namespace: Namespace name
    :type namespace: str
    :param logger: logger
    :type logger: <class 'kopf._core.actions.loggers.ObjectLogger'>
    :param labels: labels
    :type labels: dict
    :return: Response (status:created, pending, error, unauthorized)
    :rtype: dict
    '''
    body = {
                  "apiVersion": "rbac.authorization.k8s.io/v1",
                  "kind": "RoleBinding",
                  "metadata": {
                    "name": name,
                    "labels": labels,
                    "namespace": namespace
                  },
                  "subjects": [
                    {
                      "kind": "ServiceAccount",
                      "name": sa_name
                    }
                  ],
                  "roleRef": {
                    "kind": "Role",
                    "name": role_name,
                    "apiGroup": "rbac.authorization.k8s.io"
                  }
                }

    headers = {"Content-type": "application/json",
        "Accept": "application/json",
        "Authorization": "Bearer {}".format(TOKEN)}
    r=requests.post(f"{KUBERNETES_BASE_URL}/apis/rbac.authorization.k8s.io/v1/namespaces/{namespace}/rolebindings", headers=headers, json=body, verify=HTTPS_VERIFY)
    logger.debug(f"Response of the request {r.request.url} response {r.json()}")
    if r.status_code in [200,201]:
        Response = {'status':True}
    elif r.status_code == 202:
        Response = {'status':False}
    elif r.status_code == 401:
        Response = {'status': False}
    else:
        Response = {'status':False}
    return Response

def get_role_binding(name: str=None, namespace: str=None, logger=None):
    '''
    :param name: name of the role
    :type name: str
    :param namespace: Namespace name
    :type namespace: str
    :param logger: logger
    :type logger: <class 'kopf._core.actions.loggers.ObjectLogger'>
    :return: Response
    :rtype: dict
    '''
    headers = {"Accept": "application/json",
        "Authorization": "Bearer {}".format(TOKEN)}
    r=requests.get(f"{KUBERNETES_BASE_URL}/apis/rbac.authorization.k8s.io/v1/namespaces/{namespace}/rolebindings/{name}", headers=headers, verify=HTTPS_VERIFY)
    logger.debug(f"Response of the request {r.request.url} response {r.json()}")
    if r.status_code in [200,204]:
        Response = {'status':True}
    elif r.status_code == 202:
        Response = {'status':False}
    elif r.status_code == 401:
        Response = {'status': False}
    else:
        Response = {'status':False}
    return Response

#Delete
def delete_role_binding(name: str=None, namespace: str=None, logger=None):
    '''
    :param name: name of the role
    :type name: str
    :param namespace: Namespace name
    :type namespace: str
    :param logger: logger
    :type logger: <class 'kopf._core.actions.loggers.ObjectLogger'>
    :return: Response
    :rtype: dict
    '''
    headers = {"Accept": "application/json",
        "Authorization": "Bearer {}".format(TOKEN)}
    r=requests.delete(f"{KUBERNETES_BASE_URL}/apis/rbac.authorization.k8s.io/v1/namespaces/{namespace}/rolebindings/{name}", headers=headers, verify=HTTPS_VERIFY)
    logger.debug(f"Response of the request {r.request.url} response {r.json()}")
    if r.status_code in [200,204]:
        Response = {'status':True}
    elif r.status_code == 202:
        Response = {'status':False}
    elif r.status_code == 401:
        Response = {'status': False}
    else:
        Response = {'status':False}
    return Response
    