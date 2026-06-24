package k8scontroller

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"

	"cla-platform/services/environment-controller/internal/labcontroller"
)

type RouteRegistry interface {
	RegisterRoute(ctx context.Context, attemptID string, epoch int, route labcontroller.RouteRegistration) error
	UnregisterRoute(ctx context.Context, attemptID string, epoch int, routeRef string) error
	RevokeTickets(ctx context.Context, attemptID string, epoch int, routeRef string) error
}

type ControlPlaneRouteRegistry struct {
	APIURL       string
	ServiceToken string
	HTTP         *http.Client
}

func (r ControlPlaneRouteRegistry) RegisterRoute(ctx context.Context, attemptID string, epoch int, route labcontroller.RouteRegistration) error {
	if r.APIURL == "" {
		return fmt.Errorf("control-plane API URL is required for route registration")
	}
	body, err := json.Marshal(map[string]any{
		"routeRef": route.RouteRef,
		"endpoint": serviceEndpoint(
			route.Namespace,
			route.ServiceName,
			route.Port,
		),
		"protocol": "tcp-sessionwire",
	})
	if err != nil {
		return err
	}
	return r.post(ctx, attemptID, epoch, "/route", body)
}

func (r ControlPlaneRouteRegistry) UnregisterRoute(ctx context.Context, attemptID string, epoch int, routeRef string) error {
	if r.APIURL == "" {
		return fmt.Errorf("control-plane API URL is required for route unregistration")
	}
	body, err := json.Marshal(map[string]any{"routeRef": routeRef})
	if err != nil {
		return err
	}
	return r.post(ctx, attemptID, epoch, "/route/unregister", body)
}

func (r ControlPlaneRouteRegistry) RevokeTickets(ctx context.Context, attemptID string, epoch int, routeRef string) error {
	if r.APIURL == "" {
		return fmt.Errorf("control-plane API URL is required for ticket revocation")
	}
	body, err := json.Marshal(map[string]any{"routeRef": routeRef})
	if err != nil {
		return err
	}
	return r.post(ctx, attemptID, epoch, "/tickets/revoke", body)
}

func (r ControlPlaneRouteRegistry) post(ctx context.Context, attemptID string, epoch int, suffix string, body []byte) error {
	endpoint := strings.TrimRight(r.APIURL, "/") +
		"/internal/attempts/" +
		url.PathEscape(attemptID) +
		"/sessions/" +
		strconv.Itoa(epoch) +
		suffix
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, endpoint, bytes.NewReader(body))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-CLA-Service-Token", r.ServiceToken)
	client := r.HTTP
	if client == nil {
		client = &http.Client{Timeout: 5 * time.Second}
	}
	resp, err := client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("control-plane route registry status %d", resp.StatusCode)
	}
	return nil
}

func serviceEndpoint(namespace, serviceName string, port int) string {
	return serviceName + "." + namespace + ".svc.cluster.local:" + strconv.Itoa(port)
}
