import * as React from "react";
import { Bell, AlertTriangle, Copy, CalendarClock, Check, Trash2 } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { useSubscriptions, useDeleteSubscription } from "@/hooks/useSubscriptions";
import { useNotifications, useMarkNotificationRead, useDismissNotification } from "@/hooks/useNotifications";
import { useAuth } from "@/contexts/AuthContext";
import { daysUntil, formatDate, formatPrice } from "@/lib/format";
import { cn } from "@/lib/utils";

interface ClientAlert {
  id: string;
  type: "trial" | "duplicate";
  message: string;
}

/** Alertes calculées côté client depuis les abonnements réels déjà chargés
 * (essai qui se termine, doublon de domaine) -- distinctes des alertes de
 * renouvellement (persistées côté serveur, cf. useNotifications) car
 * purement informatives et jamais dédupliquées/acquittées individuellement. */
function computeClientAlerts(subscriptions: ReturnType<typeof useSubscriptions>["data"]): ClientAlert[] {
  if (!subscriptions) return [];
  const alerts: ClientAlert[] = [];

  for (const sub of subscriptions) {
    if (sub.trial_end_date) {
      const days = daysUntil(sub.trial_end_date);
      if (days >= 0 && days <= 7) {
        alerts.push({
          id: `trial-${sub.id}`,
          type: "trial",
          message: `L'essai de ${sub.name} se termine dans ${days} jour${days > 1 ? "s" : ""}`,
        });
      }
    }
  }

  const byDomain = new Map<string, number>();
  for (const sub of subscriptions) {
    if (!sub.domain) continue;
    byDomain.set(sub.domain, (byDomain.get(sub.domain) ?? 0) + 1);
  }
  for (const [domain, count] of byDomain) {
    if (count > 1) {
      alerts.push({ id: `dup-${domain}`, type: "duplicate", message: `${count} abonnements actifs sur ${domain}` });
    }
  }

  return alerts;
}

export interface NotificationCenterProps {
  /** Style du bouton déclencheur -- surchargeable pour s'intégrer sur un
   * fond sombre (ex: TopNavbar) plutôt que sur un fond clair. */
  triggerClassName?: string;
}

export function NotificationCenter({ triggerClassName }: NotificationCenterProps = {}) {
  const { user } = useAuth();
  const { data: subscriptions } = useSubscriptions();
  const { data: renewalAlerts } = useNotifications();
  const markRead = useMarkNotificationRead();
  const dismiss = useDismissNotification();
  const deleteSubscription = useDeleteSubscription();
  const queryClient = useQueryClient();
  const [open, setOpen] = React.useState(false);

  const clientAlerts = computeClientAlerts(subscriptions);
  const alerts = renewalAlerts ?? [];
  const unreadCount = alerts.filter((a) => !a.is_read).length;

  async function handleOpen() {
    const next = !open;
    setOpen(next);
    if (next) {
      // mutateAsync + Promise.allSettled plutôt qu'un .mutate() par alerte :
      // chaque mutation réussie invalidait indépendamment ["notifications"],
      // déclenchant potentiellement N GET /notifications en cascade au lieu
      // d'un seul une fois toutes les alertes marquées lues.
      const unread = alerts.filter((a) => !a.is_read);
      if (unread.length > 0) {
        await Promise.allSettled(unread.map((a) => markRead.mutateAsync(a.id)));
      }
    }
  }

  function handleRenewNow(alertId: string) {
    dismiss.mutate(alertId);
  }

  function handleDeleteSubscription(subscriptionId: string) {
    deleteSubscription.mutate(subscriptionId, {
      onSuccess: () => {
        // La suppression de l'abonnement supprime déjà la ligne côté serveur
        // (cascade FK) -- on invalide juste le cache local pour la faire
        // disparaître immédiatement, sans dépendre du prochain refetch.
        queryClient.invalidateQueries({ queryKey: ["notifications"] });
      },
    });
  }

  const hasAnyAlert = alerts.length > 0 || clientAlerts.length > 0;

  return (
    <div className="relative">
      <button
        onClick={handleOpen}
        className={cn(
          "relative flex h-9 w-9 items-center justify-center rounded-full text-text-muted hover:bg-surface-hover hover:text-text-main",
          triggerClassName
        )}
        aria-label="Notifications"
      >
        <Bell className="h-4 w-4" />
        {unreadCount > 0 && (
          <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-red-500 px-1 text-[10px] font-semibold text-white">
            {unreadCount > 9 ? "9+" : unreadCount}
          </span>
        )}
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute right-0 z-50 mt-2 w-96 rounded-lg border border-border bg-surface p-2 shadow-lg">
            <p className="px-2 py-1.5 text-xs font-semibold text-text-muted">Notifications</p>
            {!hasAnyAlert ? (
              <p className="px-2 py-4 text-center text-sm text-text-muted">Rien à signaler.</p>
            ) : (
              <ul className="max-h-96 space-y-1 overflow-y-auto">
                {alerts.map((alert) => (
                  <li key={alert.id} className="rounded-sm px-2 py-2 text-sm">
                    <div className="flex items-start gap-2 text-primary">
                      <CalendarClock className="mt-0.5 h-4 w-4 shrink-0" />
                      <div className="min-w-0 flex-1">
                        <p className="text-text-main">
                          <span className="font-medium">{alert.subscription_name}</span> se renouvelle le{" "}
                          {formatDate(alert.renewal_date)}
                        </p>
                        <p className="text-xs text-text-muted">{formatPrice(alert.price, user?.currency)}</p>
                        <div className="mt-1.5 flex gap-2">
                          <button
                            onClick={() => handleRenewNow(alert.id)}
                            className="inline-flex items-center gap-1 rounded-sm bg-primary/10 px-2 py-1 text-xs font-medium text-primary hover:bg-primary/20"
                          >
                            <Check className="h-3 w-3" /> Renouveler maintenant
                          </button>
                          <button
                            onClick={() => handleDeleteSubscription(alert.subscription_id)}
                            className="inline-flex items-center gap-1 rounded-sm bg-red-50 px-2 py-1 text-xs font-medium text-red-600 hover:bg-red-100"
                          >
                            <Trash2 className="h-3 w-3" /> Supprimer
                          </button>
                        </div>
                      </div>
                    </div>
                  </li>
                ))}
                {clientAlerts.map((alert) => (
                  <li
                    key={alert.id}
                    className={cn(
                      "flex items-start gap-2 rounded-sm px-2 py-2 text-sm",
                      alert.type === "trial" ? "text-amber-700" : "text-primary"
                    )}
                  >
                    {alert.type === "trial" ? (
                      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                    ) : (
                      <Copy className="mt-0.5 h-4 w-4 shrink-0" />
                    )}
                    {alert.message}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}
    </div>
  );
}
