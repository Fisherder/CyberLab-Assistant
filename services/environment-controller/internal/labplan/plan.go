package labplan

import (
	"fmt"
	"regexp"
	"strconv"
	"strings"

	cla "cla-platform/services/environment-controller/api/v1"
)

const (
	DefaultWorkspaceImage = "cla/workspace-web@sha256:dev-fixture"
	DefaultTargetImage    = "cla/web-sqli-target@sha256:dev-fixture"
	DefaultRuntimeClass   = "gvisor"
)

type Metadata struct {
	Name      string            `json:"name"`
	Namespace string            `json:"namespace,omitempty"`
	Labels    map[string]string `json:"labels,omitempty"`
}

type Object struct {
	APIVersion string         `json:"apiVersion"`
	Kind       string         `json:"kind"`
	Metadata   Metadata       `json:"metadata"`
	Spec       map[string]any `json:"spec,omitempty"`
	StringData map[string]string
}

type ImageSet struct {
	Workspace string
	Target    string
}

type SecretSet struct {
	TargetSessionKey string
}

func Plan(spec cla.LabSessionSpec, images ImageSet, secrets SecretSet) ([]Object, error) {
	if spec.WorkspaceType != cla.WorkspaceTerminal {
		return nil, fmt.Errorf("workspace type %q is not enabled in phase one", spec.WorkspaceType)
	}
	if spec.TenantID == "" || spec.AttemptID == "" || spec.Epoch < 1 || spec.RouteRef == "" {
		return nil, fmt.Errorf("tenant, attempt, epoch, and routeRef are required")
	}
	runtimeClassName := spec.RuntimeClassName
	if runtimeClassName == "" {
		runtimeClassName = DefaultRuntimeClass
	}
	if images.Workspace == "" {
		images.Workspace = DefaultWorkspaceImage
	}
	if images.Target == "" {
		images.Target = DefaultTargetImage
	}
	if secrets.TargetSessionKey == "" {
		return nil, fmt.Errorf("target session key is required")
	}

	namespace := NamespaceName(spec)
	labels := map[string]string{
		"cla.edu/tenant-id":  spec.TenantID,
		"cla.edu/attempt-id": spec.AttemptID,
		"cla.edu/epoch":      strconv.Itoa(spec.Epoch),
		"cla.edu/route-ref":  spec.RouteRef,
	}
	return []Object{
		namespaceObject(namespace, labels),
		resourceQuota(namespace, labels),
		limitRange(namespace, labels),
		sessionSecret(namespace, labels, secrets),
		defaultDenyNetworkPolicy(namespace, labels),
		gatewayToWorkspacePolicy(namespace, labels),
		workspaceToTargetPolicy(namespace, labels),
		workspaceService(namespace, labels),
		targetService(namespace, labels),
		workspaceDeployment(namespace, labels, runtimeClassName, images.Workspace),
		targetDeployment(namespace, labels, runtimeClassName, images.Target),
	}, nil
}

func NamespaceName(spec cla.LabSessionSpec) string {
	attempt := sanitizeName(spec.AttemptID)
	if len(attempt) > 28 {
		attempt = attempt[:28]
	}
	return fmt.Sprintf("lab-%s-e%d", attempt, spec.Epoch)
}

func namespaceObject(name string, labels map[string]string) Object {
	return Object{
		APIVersion: "v1",
		Kind:       "Namespace",
		Metadata: Metadata{
			Name: name,
			Labels: merge(labels, map[string]string{
				"pod-security.kubernetes.io/enforce": "restricted",
				"pod-security.kubernetes.io/audit":   "restricted",
				"pod-security.kubernetes.io/warn":    "restricted",
			}),
		},
	}
}

func resourceQuota(namespace string, labels map[string]string) Object {
	return Object{
		APIVersion: "v1",
		Kind:       "ResourceQuota",
		Metadata:   namespaced("lab-quota", namespace, labels),
		Spec: map[string]any{
			"hard": map[string]string{
				"pods":                       "4",
				"requests.cpu":               "1000m",
				"requests.memory":            "1Gi",
				"requests.ephemeral-storage": "2Gi",
				"limits.cpu":                 "2000m",
				"limits.memory":              "2Gi",
			},
		},
	}
}

func limitRange(namespace string, labels map[string]string) Object {
	return Object{
		APIVersion: "v1",
		Kind:       "LimitRange",
		Metadata:   namespaced("lab-limits", namespace, labels),
		Spec: map[string]any{
			"limits": []map[string]any{
				{
					"type": "Container",
					"defaultRequest": map[string]string{
						"cpu":    "100m",
						"memory": "128Mi",
					},
					"default": map[string]string{
						"cpu":    "500m",
						"memory": "768Mi",
					},
				},
			},
		},
	}
}

func sessionSecret(namespace string, labels map[string]string, secrets SecretSet) Object {
	return Object{
		APIVersion: "v1",
		Kind:       "Secret",
		Metadata:   namespaced("target-session", namespace, labels),
		Spec: map[string]any{
			"type": "Opaque",
		},
		StringData: map[string]string{
			"TARGET_SESSION_KEY": secrets.TargetSessionKey,
		},
	}
}

func defaultDenyNetworkPolicy(namespace string, labels map[string]string) Object {
	return Object{
		APIVersion: "networking.k8s.io/v1",
		Kind:       "NetworkPolicy",
		Metadata:   namespaced("default-deny", namespace, labels),
		Spec: map[string]any{
			"podSelector": map[string]any{},
			"policyTypes": []string{"Ingress", "Egress"},
		},
	}
}

func gatewayToWorkspacePolicy(namespace string, labels map[string]string) Object {
	return Object{
		APIVersion: "networking.k8s.io/v1",
		Kind:       "NetworkPolicy",
		Metadata:   namespaced("allow-gateway-to-workspace", namespace, labels),
		Spec: map[string]any{
			"podSelector": matchLabels(map[string]string{"app": "workspace"}),
			"policyTypes": []string{"Ingress"},
			"ingress": []map[string]any{
				{
					"from": []map[string]any{
						{"namespaceSelector": matchLabels(map[string]string{"cla.edu/system": "true"})},
					},
					"ports": []map[string]any{{"protocol": "TCP", "port": 7777}},
				},
			},
		},
	}
}

func workspaceToTargetPolicy(namespace string, labels map[string]string) Object {
	return Object{
		APIVersion: "networking.k8s.io/v1",
		Kind:       "NetworkPolicy",
		Metadata:   namespaced("allow-workspace-to-target", namespace, labels),
		Spec: map[string]any{
			"podSelector": matchLabels(map[string]string{"app": "target"}),
			"policyTypes": []string{"Ingress"},
			"ingress": []map[string]any{
				{
					"from": []map[string]any{
						{"podSelector": matchLabels(map[string]string{"app": "workspace"})},
					},
					"ports": []map[string]any{{"protocol": "TCP", "port": 8080}},
				},
			},
		},
	}
}

func workspaceService(namespace string, labels map[string]string) Object {
	return Object{
		APIVersion: "v1",
		Kind:       "Service",
		Metadata:   namespaced("workspace-sessiond", namespace, labels),
		Spec: map[string]any{
			"type":     "ClusterIP",
			"selector": map[string]string{"app": "workspace"},
			"ports": []map[string]any{
				{"name": "sessiond", "port": 7777, "targetPort": 7777, "protocol": "TCP"},
			},
		},
	}
}

func targetService(namespace string, labels map[string]string) Object {
	return Object{
		APIVersion: "v1",
		Kind:       "Service",
		Metadata:   namespaced("target-http", namespace, labels),
		Spec: map[string]any{
			"type":     "ClusterIP",
			"selector": map[string]string{"app": "target"},
			"ports": []map[string]any{
				{"name": "http", "port": 8080, "targetPort": 8080, "protocol": "TCP"},
			},
		},
	}
}

func workspaceDeployment(namespace string, labels map[string]string, runtimeClassName, image string) Object {
	return deployment(namespace, "workspace", labels, runtimeClassName, map[string]any{
		"name":  "workspace",
		"image": image,
		"ports": []map[string]any{{"name": "sessiond", "containerPort": 7777}},
		"env": []map[string]string{
			{"name": "TARGET_BASE_URL", "value": "http://target-http:8080"},
		},
		"volumeMounts":    []map[string]string{{"name": "workspace-tmp", "mountPath": "/tmp"}},
		"securityContext": containerSecurityContext(),
	}, []map[string]any{{"name": "workspace-tmp", "emptyDir": map[string]string{}}})
}

func targetDeployment(namespace string, labels map[string]string, runtimeClassName, image string) Object {
	return deployment(namespace, "target", labels, runtimeClassName, map[string]any{
		"name":  "target",
		"image": image,
		"ports": []map[string]any{{"name": "http", "containerPort": 8080}},
		"env": []map[string]any{
			{
				"name": "TARGET_SESSION_KEY",
				"valueFrom": map[string]any{
					"secretKeyRef": map[string]string{
						"name": "target-session",
						"key":  "TARGET_SESSION_KEY",
					},
				},
			},
		},
		"volumeMounts":    []map[string]string{{"name": "target-tmp", "mountPath": "/tmp"}},
		"securityContext": containerSecurityContext(),
	}, []map[string]any{{"name": "target-tmp", "emptyDir": map[string]string{}}})
}

func deployment(namespace, app string, labels map[string]string, runtimeClassName string, container map[string]any, volumes []map[string]any) Object {
	podLabels := merge(labels, map[string]string{"app": app})
	return Object{
		APIVersion: "apps/v1",
		Kind:       "Deployment",
		Metadata:   namespaced(app, namespace, labels),
		Spec: map[string]any{
			"replicas": 1,
			"selector": matchLabels(map[string]string{"app": app}),
			"template": map[string]any{
				"metadata": map[string]any{"labels": podLabels},
				"spec": map[string]any{
					"runtimeClassName":             runtimeClassName,
					"automountServiceAccountToken": false,
					"securityContext": map[string]any{
						"runAsNonRoot": true,
						"runAsUser":    10001,
						"runAsGroup":   10001,
						"fsGroup":      10001,
						"seccompProfile": map[string]string{
							"type": "RuntimeDefault",
						},
					},
					"containers": []map[string]any{container},
					"volumes":    volumes,
				},
			},
		},
	}
}

func containerSecurityContext() map[string]any {
	return map[string]any{
		"runAsNonRoot":             true,
		"runAsUser":                10001,
		"runAsGroup":               10001,
		"allowPrivilegeEscalation": false,
		"readOnlyRootFilesystem":   true,
		"capabilities": map[string][]string{
			"drop": []string{"ALL"},
		},
		"seccompProfile": map[string]string{
			"type": "RuntimeDefault",
		},
	}
}

func namespaced(name, namespace string, labels map[string]string) Metadata {
	return Metadata{Name: name, Namespace: namespace, Labels: labels}
}

func matchLabels(labels map[string]string) map[string]any {
	return map[string]any{"matchLabels": labels}
}

func merge(left map[string]string, right map[string]string) map[string]string {
	out := map[string]string{}
	for key, value := range left {
		out[key] = value
	}
	for key, value := range right {
		out[key] = value
	}
	return out
}

func sanitizeName(value string) string {
	lower := strings.ToLower(value)
	re := regexp.MustCompile(`[^a-z0-9-]+`)
	cleaned := strings.Trim(re.ReplaceAllString(lower, "-"), "-")
	if cleaned == "" {
		return "attempt"
	}
	return cleaned
}
