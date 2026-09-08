import * as React from "react";
import { toast } from "sonner";
import { Trash2, ShieldCheck, ShieldOff } from "lucide-react";
import {
  AdminDrawer,
  AdminDrawerContent,
  AdminDrawerHeader,
  AdminDrawerTitle,
  AdminDrawerDescription,
  AdminDrawerBody,
  AdminDrawerFooter,
} from "@/components/admin/AdminDrawer";
import { useAdminUpdateUser, useAdminUserSubscriptions, useAdminUpdateUserSubscription, useAdminDeleteUserSubscription } from "@/hooks/useAdmin";
import { formatPrice } from "@/lib/format";
import { getErrorMessage } from "@/api/axiosClient";
import type { AdminUser, Subscription } from "@/types";

export interface AdminUserEditDrawerProps {
  user: AdminUser | null;
  onOpenChange: (open: boolean) => void;
}

/** Panneau d'édition CRM : informations de base, bascule Premium/Admin, et
 * gestion des abonnements détectés pour cet utilisateur précis (correction
 * ou suppression en cas de faux positif de l'algorithme bancaire). */
export function AdminUserEditDrawer({ user, onOpenChange }: AdminUserEditDrawerProps) {
  const [email, setEmail] = React.useState("");
  const [firstName, setFirstName] = React.useState("");

  // Dépend de l'id, pas de la référence `user` : un toggle Premium/Admin
  // invalide ["admin","users"] et renvoie un nouvel objet `user` (même id)
  // -- se resynchroniser sur [user] écraserait la saisie Email/Prénom en
  // cours si l'admin tape pendant que ce refetch arrive.
  const userId = user?.id;
  React.useEffect(() => {
    if (user) {
      setEmail(user.email);
      setFirstName(user.first_name);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId]);

  const updateUser = useAdminUpdateUser();
  const subscriptionsQuery = useAdminUserSubscriptions(user?.id);
  const updateSubscription = useAdminUpdateUserSubscription(user?.id);
  const deleteSubscription = useAdminDeleteUserSubscription(user?.id);

  if (!user) return null;

  function saveBasicInfo() {
    if (!user) return;
    const patch: { email?: string; first_name?: string } = {};
    if (email !== user.email) patch.email = email;
    if (firstName !== user.first_name) patch.first_name = firstName;
    if (Object.keys(patch).length === 0) return;

    updateUser.mutate(
      { id: user.id, input: patch },
      {
        onSuccess: () => toast.success("Informations mises à jour."),
        onError: (error) => toast.error(getErrorMessage(error)),
      }
    );
  }

  function togglePremium() {
    if (!user) return;
    updateUser.mutate(
      { id: user.id, input: { is_premium: !user.is_premium } },
      {
        onSuccess: (updated) =>
          toast.success(updated.is_premium ? "Statut Premium activé." : "Statut Premium désactivé."),
        onError: (error) => toast.error(getErrorMessage(error)),
      }
    );
  }

  function toggleAdmin() {
    if (!user) return;
    updateUser.mutate(
      { id: user.id, input: { is_admin: !user.is_admin } },
      {
        onSuccess: (updated) =>
          toast.success(updated.is_admin ? "Droits administrateur accordés." : "Droits administrateur retirés."),
        onError: (error) => toast.error(getErrorMessage(error)),
      }
    );
  }

  function handleDeleteSubscription(subscription: Subscription) {
    if (!user) return;
    if (!window.confirm(`Supprimer "${subscription.name}" du compte de ${user.email} ?`)) return;
    deleteSubscription.mutate(subscription.id, {
      onSuccess: () => toast.success(`"${subscription.name}" supprimé.`),
      onError: (error) => toast.error(getErrorMessage(error)),
    });
  }

  function handleSubscriptionFieldChange(subscription: Subscription, field: "price" | "billing_day", value: number) {
    updateSubscription.mutate(
      { subId: subscription.id, input: { ...subscription, [field]: value } },
      { onError: (error) => toast.error(getErrorMessage(error)) }
    );
  }

  return (
    <AdminDrawer open={!!user} onOpenChange={onOpenChange}>
      <AdminDrawerContent>
        <AdminDrawerHeader>
          <AdminDrawerTitle>Éditer {user.first_name}</AdminDrawerTitle>
          <AdminDrawerDescription>{user.email}</AdminDrawerDescription>
        </AdminDrawerHeader>

        <AdminDrawerBody>
          {/* Informations de base */}
          <section className="space-y-3">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500">Informations</h3>
            <div>
              <label className="mb-1 block text-xs text-slate-400">Email</label>
              <input
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                onBlur={saveBasicInfo}
                className="w-full rounded-md border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-100 focus:border-amber-500 focus:outline-none"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs text-slate-400">Prénom</label>
              <input
                value={firstName}
                onChange={(e) => setFirstName(e.target.value)}
                onBlur={saveBasicInfo}
                className="w-full rounded-md border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-100 focus:border-amber-500 focus:outline-none"
              />
            </div>
          </section>

          {/* Statut Premium */}
          <section className="space-y-3">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500">Statut</h3>
            <button
              onClick={togglePremium}
              disabled={updateUser.isPending}
              className="flex w-full items-center justify-between rounded-md border border-slate-700 bg-slate-800 px-3 py-2.5 transition-colors hover:border-slate-600 disabled:opacity-60"
            >
              <span className="flex items-center gap-2 text-sm text-slate-200">
                {user.is_premium ? (
                  <ShieldCheck className="h-4 w-4 text-emerald-400" />
                ) : (
                  <ShieldOff className="h-4 w-4 text-slate-500" />
                )}
                Membre Premium
              </span>
              <span
                className={`relative h-5 w-9 rounded-full transition-colors ${user.is_premium ? "bg-emerald-500" : "bg-slate-700"}`}
              >
                <span
                  className={`absolute top-0.5 h-4 w-4 rounded-full bg-white transition-transform ${user.is_premium ? "translate-x-4" : "translate-x-0.5"}`}
                />
              </span>
            </button>

            <button
              onClick={toggleAdmin}
              disabled={updateUser.isPending}
              className="flex w-full items-center justify-between rounded-md border border-slate-700 bg-slate-800 px-3 py-2.5 transition-colors hover:border-slate-600 disabled:opacity-60"
            >
              <span className="flex items-center gap-2 text-sm text-slate-200">
                <ShieldAlertIcon isAdmin={user.is_admin} />
                Administrateur
              </span>
              <span
                className={`relative h-5 w-9 rounded-full transition-colors ${user.is_admin ? "bg-amber-500" : "bg-slate-700"}`}
              >
                <span
                  className={`absolute top-0.5 h-4 w-4 rounded-full bg-white transition-transform ${user.is_admin ? "translate-x-4" : "translate-x-0.5"}`}
                />
              </span>
            </button>
          </section>

          {/* Abonnements détectés */}
          <section className="space-y-3">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500">
              Abonnements ({subscriptionsQuery.data?.length ?? 0})
            </h3>

            {subscriptionsQuery.isPending && <p className="text-sm text-slate-500">Chargement…</p>}
            {subscriptionsQuery.isError && <p className="text-sm text-red-400">Impossible de charger les abonnements.</p>}
            {subscriptionsQuery.data?.length === 0 && (
              <p className="text-sm text-slate-500">Aucun abonnement pour ce compte.</p>
            )}

            <div className="space-y-2">
              {subscriptionsQuery.data?.map((subscription) => (
                <div key={subscription.id} className="rounded-md border border-slate-700 bg-slate-800 p-3">
                  <div className="flex items-center justify-between gap-2">
                    <p className="truncate text-sm font-medium text-slate-100">{subscription.name}</p>
                    <button
                      onClick={() => handleDeleteSubscription(subscription)}
                      aria-label={`Supprimer ${subscription.name}`}
                      className="shrink-0 rounded p-1 text-slate-500 transition-colors hover:bg-red-500/10 hover:text-red-400"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                  <div className="mt-2 flex items-center gap-3 text-xs">
                    <label className="flex items-center gap-1.5 text-slate-400">
                      Prix
                      <input
                        type="number"
                        step="0.01"
                        defaultValue={subscription.price}
                        onBlur={(e) => {
                          const value = parseFloat(e.target.value);
                          if (!Number.isNaN(value) && value !== subscription.price) {
                            handleSubscriptionFieldChange(subscription, "price", value);
                          }
                        }}
                        className="w-20 rounded border border-slate-700 bg-slate-900 px-2 py-1 text-slate-100 focus:border-amber-500 focus:outline-none"
                      />
                    </label>
                    <label className="flex items-center gap-1.5 text-slate-400">
                      Jour
                      <input
                        type="number"
                        min={1}
                        max={31}
                        defaultValue={subscription.billing_day}
                        onBlur={(e) => {
                          const value = parseInt(e.target.value, 10);
                          if (!Number.isNaN(value) && value !== subscription.billing_day) {
                            handleSubscriptionFieldChange(subscription, "billing_day", value);
                          }
                        }}
                        className="w-14 rounded border border-slate-700 bg-slate-900 px-2 py-1 text-slate-100 focus:border-amber-500 focus:outline-none"
                      />
                    </label>
                    <span className="ml-auto text-slate-500">{formatPrice(subscription.price)}</span>
                  </div>
                </div>
              ))}
            </div>
          </section>
        </AdminDrawerBody>

        <AdminDrawerFooter>
          <button
            onClick={() => onOpenChange(false)}
            className="rounded-md border border-slate-700 bg-slate-800 px-4 py-2 text-sm text-slate-300 transition-colors hover:bg-slate-700"
          >
            Fermer
          </button>
        </AdminDrawerFooter>
      </AdminDrawerContent>
    </AdminDrawer>
  );
}

function ShieldAlertIcon({ isAdmin }: { isAdmin: boolean }) {
  return isAdmin ? (
    <ShieldCheck className="h-4 w-4 text-amber-400" />
  ) : (
    <ShieldOff className="h-4 w-4 text-slate-500" />
  );
}
