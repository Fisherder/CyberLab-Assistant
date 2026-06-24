package labplan

import (
	"encoding/json"
	"strings"
	"testing"

	cla "cla-platform/services/environment-controller/api/v1"
)

func TestPlanCreatesIsolatedNamespaceAndRequiredObjects(t *testing.T) {
	objects, err := Plan(defaultSpec(), ImageSet{}, SecretSet{TargetSessionKey: "session-secret"})
	if err != nil {
		t.Fatalf("plan failed: %v", err)
	}
	byKindName := index(objects)
	namespace := byKindName["Namespace/lab-a-123-e2"]
	if namespace.Kind == "" {
		t.Fatalf("namespace not planned: %#v", byKindName)
	}
	if namespace.Metadata.Labels["pod-security.kubernetes.io/enforce"] != "restricted" {
		t.Fatalf("namespace missing restricted pod security labels: %#v", namespace.Metadata.Labels)
	}
	for _, key := range []string{
		"ResourceQuota/lab-quota",
		"LimitRange/lab-limits",
		"Secret/target-session",
		"NetworkPolicy/default-deny",
		"NetworkPolicy/allow-gateway-to-workspace",
		"NetworkPolicy/allow-workspace-to-target",
		"Service/workspace-sessiond",
		"Service/target-http",
		"Deployment/workspace",
		"Deployment/target",
	} {
		object := byKindName[key]
		if object.Kind == "" {
			t.Fatalf("missing object %s", key)
		}
		if object.Metadata.Namespace != namespace.Metadata.Name && object.Kind != "Namespace" {
			t.Fatalf("%s not scoped to session namespace: %#v", key, object.Metadata)
		}
	}
	secret := byKindName["Secret/target-session"]
	if secret.StringData["TARGET_SESSION_KEY"] != "session-secret" {
		t.Fatalf("secret data not planned")
	}
	if namespace.Metadata.Labels["TARGET_SESSION_KEY"] != "" {
		t.Fatalf("secret leaked into namespace labels")
	}
}

func TestPlanAppliesRuntimeClassAndRestrictedPodSecurity(t *testing.T) {
	objects, err := Plan(defaultSpec(), ImageSet{}, SecretSet{TargetSessionKey: "session-secret"})
	if err != nil {
		t.Fatalf("plan failed: %v", err)
	}
	for _, key := range []string{"Deployment/workspace", "Deployment/target"} {
		deploy := index(objects)[key]
		podSpec := deploy.Spec["template"].(map[string]any)["spec"].(map[string]any)
		if podSpec["runtimeClassName"] != "gvisor" {
			t.Fatalf("%s runtime class = %#v", key, podSpec["runtimeClassName"])
		}
		if podSpec["automountServiceAccountToken"] != false {
			t.Fatalf("%s automounts service account token", key)
		}
		podSecurity := podSpec["securityContext"].(map[string]any)
		if podSecurity["runAsNonRoot"] != true || podSecurity["runAsUser"] != 10001 {
			t.Fatalf("%s bad pod security context %#v", key, podSecurity)
		}
		container := podSpec["containers"].([]map[string]any)[0]
		security := container["securityContext"].(map[string]any)
		if security["allowPrivilegeEscalation"] != false {
			t.Fatalf("%s allows privilege escalation", key)
		}
		if security["readOnlyRootFilesystem"] != true {
			t.Fatalf("%s root filesystem is not read-only", key)
		}
		caps := security["capabilities"].(map[string][]string)
		if len(caps["drop"]) != 1 || caps["drop"][0] != "ALL" {
			t.Fatalf("%s does not drop all capabilities: %#v", key, caps)
		}
	}
}

func TestPlanNetworkPoliciesDefaultDenyAndAllowOnlyDeclaredFlows(t *testing.T) {
	objects, err := Plan(defaultSpec(), ImageSet{}, SecretSet{TargetSessionKey: "session-secret"})
	if err != nil {
		t.Fatalf("plan failed: %v", err)
	}
	defaultDeny := index(objects)["NetworkPolicy/default-deny"]
	policyTypes := defaultDeny.Spec["policyTypes"].([]string)
	if strings.Join(policyTypes, ",") != "Ingress,Egress" {
		t.Fatalf("default deny policy types = %#v", policyTypes)
	}
	gatewayPolicy := index(objects)["NetworkPolicy/allow-gateway-to-workspace"]
	encodedGateway, _ := json.Marshal(gatewayPolicy.Spec)
	if !strings.Contains(string(encodedGateway), "cla.edu/system") || !strings.Contains(string(encodedGateway), "7777") {
		t.Fatalf("gateway policy does not target workspace sessiond: %s", encodedGateway)
	}
	targetPolicy := index(objects)["NetworkPolicy/allow-workspace-to-target"]
	encodedTarget, _ := json.Marshal(targetPolicy.Spec)
	if !strings.Contains(string(encodedTarget), "workspace") || !strings.Contains(string(encodedTarget), "8080") {
		t.Fatalf("workspace target policy does not allow declared target flow: %s", encodedTarget)
	}
}

func TestPlanRejectsNonTerminalAndMissingSecret(t *testing.T) {
	spec := defaultSpec()
	spec.WorkspaceType = cla.WorkspaceRemoteDesktop
	if _, err := Plan(spec, ImageSet{}, SecretSet{TargetSessionKey: "session-secret"}); err == nil {
		t.Fatalf("remote desktop should be rejected in phase one")
	}
	spec = defaultSpec()
	if _, err := Plan(spec, ImageSet{}, SecretSet{}); err == nil {
		t.Fatalf("missing session secret should be rejected")
	}
}

func TestPlanContainsNoForbiddenPodPrivileges(t *testing.T) {
	objects, err := Plan(defaultSpec(), ImageSet{}, SecretSet{TargetSessionKey: "session-secret"})
	if err != nil {
		t.Fatalf("plan failed: %v", err)
	}
	encoded, err := json.Marshal(objects)
	if err != nil {
		t.Fatal(err)
	}
	text := string(encoded)
	for _, forbidden := range []string{
		`"privileged":true`,
		`"hostNetwork":true`,
		`"hostPID":true`,
		`"hostPath"`,
		`"automountServiceAccountToken":true`,
	} {
		if strings.Contains(text, forbidden) {
			t.Fatalf("planned object contains forbidden setting %s: %s", forbidden, text)
		}
	}
}

func defaultSpec() cla.LabSessionSpec {
	return cla.LabSessionSpec{
		TenantID:         "tenant_dev",
		AttemptID:        "a_123",
		Epoch:            2,
		WorkspaceType:    cla.WorkspaceTerminal,
		RuntimeClassName: "gvisor",
		TTLSeconds:       5400,
		RouteRef:         "route_123",
	}
}

func index(objects []Object) map[string]Object {
	out := map[string]Object{}
	for _, object := range objects {
		out[object.Kind+"/"+object.Metadata.Name] = object
	}
	return out
}
