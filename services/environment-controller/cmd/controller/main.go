package main

import (
	"log/slog"
	"os"
	"time"

	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/runtime"
	utilruntime "k8s.io/apimachinery/pkg/util/runtime"
	clientgoscheme "k8s.io/client-go/kubernetes/scheme"
	ctrl "sigs.k8s.io/controller-runtime"

	cla "cla-platform/services/environment-controller/api/v1"
	"cla-platform/services/environment-controller/internal/k8scontroller"
	"cla-platform/services/environment-controller/internal/labplan"
)

func main() {
	scheme := runtime.NewScheme()
	utilruntime.Must(clientgoscheme.AddToScheme(scheme))
	utilruntime.Must(appsv1.AddToScheme(scheme))
	utilruntime.Must(corev1.AddToScheme(scheme))
	utilruntime.Must(cla.AddToScheme(scheme))

	mgr, err := ctrl.NewManager(ctrl.GetConfigOrDie(), ctrl.Options{Scheme: scheme})
	if err != nil {
		slog.Error("unable to create manager", "error", err)
		os.Exit(1)
	}
	routes := routeRegistry()
	reconciler := &k8scontroller.Reconciler{
		Client: mgr.GetClient(),
		Scheme: mgr.GetScheme(),
		Secrets: labplan.SecretSet{
			TargetSessionKey: env("CLA_TARGET_SESSION_KEY", "dev-target-session-key"),
		},
		Routes: routes,
		Events: k8scontroller.ControlPlaneEventSink{
			APIURL:       env("CLA_API_URL", ""),
			ServiceToken: env("CLA_INTERNAL_SERVICE_TOKEN", "change-me-internal"),
		},
		Recorder: mgr.GetEventRecorderFor("cla-environment-controller"),
		Metrics:  k8scontroller.DefaultMetrics(),
	}
	if err := reconciler.SetupWithManager(mgr); err != nil {
		slog.Error("unable to setup LabSession controller", "error", err)
		os.Exit(1)
	}
	if err := mgr.Add(k8scontroller.OrphanScanner{
		Reconciler:  reconciler,
		Interval:    durationEnv("CLA_ORPHAN_SCAN_INTERVAL", k8scontroller.DefaultOrphanScanInterval),
		GracePeriod: durationEnv("CLA_ORPHAN_GRACE_PERIOD", k8scontroller.DefaultOrphanGracePeriod),
	}); err != nil {
		slog.Error("unable to setup orphan scanner", "error", err)
		os.Exit(1)
	}
	slog.Info("environment-controller starting", "controller", "LabSession")
	if err := mgr.Start(ctrl.SetupSignalHandler()); err != nil {
		slog.Error("manager stopped", "error", err)
		os.Exit(1)
	}
}

func env(key, fallback string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return fallback
}

func durationEnv(key string, fallback time.Duration) time.Duration {
	value := os.Getenv(key)
	if value == "" {
		return fallback
	}
	duration, err := time.ParseDuration(value)
	if err != nil {
		slog.Warn("invalid duration env; using fallback", "key", key, "value", value, "fallback", fallback)
		return fallback
	}
	return duration
}

func routeRegistry() k8scontroller.RouteRegistry {
	apiURL := env("CLA_API_URL", "")
	if apiURL == "" {
		return nil
	}
	return k8scontroller.ControlPlaneRouteRegistry{
		APIURL:       apiURL,
		ServiceToken: env("CLA_INTERNAL_SERVICE_TOKEN", "change-me-internal"),
	}
}
