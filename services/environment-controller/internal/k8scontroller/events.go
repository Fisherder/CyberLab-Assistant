package k8scontroller

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
	"strings"
	"time"

	cla "cla-platform/services/environment-controller/api/v1"
)

const controllerEventSource = "cla-environment-controller"

type EventSink interface {
	EmitLabStatus(ctx context.Context, event LabStatusEvent) error
}

type LabStatusEvent struct {
	TenantID          string
	AttemptID         string
	SessionEpoch      int
	LabSessionName    string
	Status            cla.LabSessionStatus
	ReconcileReason   string
	ObservedNamespace string
}

type ControlPlaneEventSink struct {
	APIURL       string
	ServiceToken string
	HTTP         *http.Client
}

func (s ControlPlaneEventSink) EmitLabStatus(ctx context.Context, event LabStatusEvent) error {
	if s.APIURL == "" || s.ServiceToken == "" || event.AttemptID == "" || event.SessionEpoch <= 0 {
		return nil
	}
	body, err := json.Marshal(map[string]any{
		"events": []map[string]any{{
			"sessionEpoch": event.SessionEpoch,
			"source":       controllerEventSource,
			"type":         "lab.status.changed",
			"payload":      labStatusPayload(event),
		}},
	})
	if err != nil {
		return err
	}
	endpoint := strings.TrimRight(s.APIURL, "/") + "/internal/attempts/" + url.PathEscape(event.AttemptID) + "/events"
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, endpoint, bytes.NewReader(body))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-CLA-Service-Token", s.ServiceToken)
	client := s.HTTP
	if client == nil {
		client = &http.Client{Timeout: 5 * time.Second}
	}
	resp, err := client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("control-plane event append status %d", resp.StatusCode)
	}
	return nil
}

func labStatusPayload(event LabStatusEvent) map[string]any {
	return map[string]any{
		"tenantId":           event.TenantID,
		"attemptId":          event.AttemptID,
		"labSessionName":     event.LabSessionName,
		"phase":              event.Status.Phase,
		"namespaceName":      event.Status.NamespaceName,
		"routeReady":         event.Status.RouteReady,
		"components":         event.Status.Components,
		"expiresAt":          event.Status.ExpiresAt,
		"conditions":         event.Status.Conditions,
		"reason":             event.Status.Reason,
		"reconcileReason":    event.ReconcileReason,
		"observedGeneration": event.Status.ObservedGeneration,
	}
}
