package k8scontroller

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	cla "cla-platform/services/environment-controller/api/v1"
)

func TestControlPlaneEventSinkPostsLabStatusEvent(t *testing.T) {
	var requestPath string
	var serviceToken string
	var body map[string]any
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requestPath = r.URL.Path
		serviceToken = r.Header.Get("X-CLA-Service-Token")
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			t.Fatalf("decode request: %v", err)
		}
		w.WriteHeader(http.StatusAccepted)
	}))
	defer server.Close()

	err := (ControlPlaneEventSink{
		APIURL:       server.URL + "/",
		ServiceToken: "svc-token",
		HTTP:         server.Client(),
	}).EmitLabStatus(context.Background(), LabStatusEvent{
		TenantID:        "tenant_dev",
		AttemptID:       "a_123",
		SessionEpoch:    2,
		LabSessionName:  "lab-a-123-e2",
		ReconcileReason: "pending",
		Status: cla.LabSessionStatus{
			Phase:              string(cla.SessionPending),
			ObservedGeneration: 7,
			NamespaceName:      "lab-a-123-e2",
			RouteReady:         false,
			Components: map[string]cla.ComponentPhase{
				"workspace": cla.ComponentPending,
			},
			ExpiresAt: "2026-06-24T11:30:00Z",
		},
	})
	if err != nil {
		t.Fatalf("emit event: %v", err)
	}
	if requestPath != "/internal/attempts/a_123/events" {
		t.Fatalf("path = %q", requestPath)
	}
	if serviceToken != "svc-token" {
		t.Fatalf("service token = %q", serviceToken)
	}
	events := body["events"].([]any)
	event := events[0].(map[string]any)
	if event["source"] != controllerEventSource || event["type"] != "lab.status.changed" {
		t.Fatalf("event envelope = %#v", event)
	}
	if int(event["sessionEpoch"].(float64)) != 2 {
		t.Fatalf("sessionEpoch = %#v", event["sessionEpoch"])
	}
	payload := event["payload"].(map[string]any)
	if payload["phase"] != string(cla.SessionPending) || payload["namespaceName"] != "lab-a-123-e2" {
		t.Fatalf("payload = %#v", payload)
	}
	if payload["reconcileReason"] != "pending" || int(payload["observedGeneration"].(float64)) != 7 {
		t.Fatalf("payload reason/generation = %#v", payload)
	}
	if _, ok := payload["endpoint"]; ok {
		t.Fatalf("payload must not include route endpoint: %#v", payload)
	}
	if _, ok := payload["routeRef"]; ok {
		t.Fatalf("payload must not include route ref: %#v", payload)
	}
}

func TestControlPlaneEventSinkRejectsNonSuccessStatus(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusServiceUnavailable)
	}))
	defer server.Close()

	err := (ControlPlaneEventSink{
		APIURL:       server.URL,
		ServiceToken: "svc-token",
		HTTP:         server.Client(),
	}).EmitLabStatus(context.Background(), LabStatusEvent{
		AttemptID:    "a_123",
		SessionEpoch: 1,
		Status:       cla.LabSessionStatus{Phase: string(cla.SessionPending)},
	})
	if err == nil {
		t.Fatalf("expected non-success status to return an error")
	}
}
