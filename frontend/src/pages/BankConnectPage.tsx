import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Lock, ShieldCheck, ArrowRight, RefreshCw, Landmark, Clock, Receipt } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "@/contexts/AuthContext";
import { useBankConnectUrl, useBankStatus, useSyncTransactions } from "@/hooks/useBank";
import { useMagnetic } from "@/hooks/useMagnetic";
import { RevealText } from "@/components/shared/RevealText";
import { OnboardingSteps } from "@/components/shared/OnboardingSteps";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { BankSecurityAssuranceModal } from "@/components/bank/BankSecurityAssuranceModal";
import { getErrorMessage } from "@/api/axiosClient";
import { formatDateTime } from "@/lib/format";

/** Page dédiée à la connexion bancaire (flow réel Powens) : design épuré,
 * un unique geste au centre de l'écran, façon intégration Plaid/Bridge. */
export function BankConnectPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const bankConnectUrl = useBankConnectUrl();
  const syncTransactions = useSyncTransactions();
  // Gaté sur bank_connected : le bloc qui consomme bankStatus.data (L83+)
  // ne s'affiche pas avant, inutile de tirer GET /bank/status à chaque
  // visite de la page tant qu'aucune banque n'est connectée.
  const bankStatus = useBankStatus(!!user?.bank_connected);
  const magneticRef = useMagnetic<HTMLButtonElement>(0.25, 16);
  const [showAssurance, setShowAssurance] = useState(false);

  function handleConnect() {
    bankConnectUrl.mutate(undefined, {
      onSuccess: (data) => {
        window.location.href = data.webview_url;
      },
      onError: (error) => toast.error(getErrorMessage(error)),
    });
  }

  /** Banque déjà connectée : le geste n'a plus de sens pour une PREMIÈRE
   * connexion (bug QA -- le bouton disait "Connecter" même une fois
   * connecté). Il relance une synchronisation des transactions, puis
   * renvoie vers Abonnements pour lancer la détection. */
  function handleResync() {
    syncTransactions.mutate(undefined, {
      onSuccess: (data) => {
        toast.success(`${data.synced_count} nouvelle(s) transaction(s) synchronisée(s).`);
        navigate("/subscriptions");
      },
      onError: (error) => toast.error(getErrorMessage(error)),
    });
  }

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-luxury-bg px-6 text-center">
      {!user?.bank_connected && <OnboardingSteps current={3} />}

      <RevealText as="h1" className="max-w-lg text-4xl font-black tracking-tight text-luxury-text sm:text-5xl">
        {user?.bank_connected ? "Ta banque est connectée" : "Sécurise ta connexion bancaire"}
      </RevealText>
      <RevealText className="mt-4 max-w-md text-base text-luxury-text-light">
        {user?.bank_connected
          ? "Tes transactions sont synchronisées automatiquement. Tu peux relancer une détection à tout moment."
          : "Un seul geste pour connecter ta banque et laisser SubSaver isoler tes abonnements récurrents."}
      </RevealText>

      {/* Repères de confiance remontés avant le geste de connexion (et non plus
       * seulement dans la modale déclenchée au clic) : agrément ACPR/DSP2 et
       * chiffrement visibles au moment où l'utilisateur évalue s'il continue. */}
      {!user?.bank_connected && (
        <div className="mt-5 flex flex-wrap items-center justify-center gap-2">
          <span className="inline-flex items-center gap-1.5 rounded-full border border-slate-900/10 bg-white px-3 py-1 text-[11px] font-semibold text-luxury-text-light shadow-sm">
            <ShieldCheck className="h-3.5 w-3.5 text-luxury-gold-deep" /> Powens, agréé ACPR
          </span>
          <span className="inline-flex items-center gap-1.5 rounded-full border border-slate-900/10 bg-white px-3 py-1 text-[11px] font-semibold text-luxury-text-light shadow-sm">
            <Lock className="h-3.5 w-3.5 text-luxury-gold-deep" /> Conforme DSP2
          </span>
          <span className="inline-flex items-center gap-1.5 rounded-full border border-slate-900/10 bg-white px-3 py-1 text-[11px] font-semibold text-luxury-text-light shadow-sm">
            Chiffrement bout-en-bout
          </span>
        </div>
      )}

      {/* Indicateurs de réassurance : établissement, dernière synchro, volume
       * -- remplace le message générique "Ta banque est connectée" qui ne
       * donnait aucune preuve concrète que la connexion fonctionne vraiment. */}
      {user?.bank_connected && (
        <div className="mt-8 grid w-full max-w-md grid-cols-1 gap-3 sm:grid-cols-3">
          {bankStatus.isPending ? (
            <>
              <Skeleton className="h-20 rounded-2xl" />
              <Skeleton className="h-20 rounded-2xl" />
              <Skeleton className="h-20 rounded-2xl" />
            </>
          ) : (
            <>
              <div className="rounded-2xl border border-slate-900/10 bg-white p-4 text-left shadow-sm">
                <div className="flex items-center gap-1.5 text-luxury-gold-deep">
                  <Landmark className="h-3.5 w-3.5" />
                  <p className="text-xs font-medium text-luxury-text-light">Établissement</p>
                </div>
                <p className="mt-1 truncate text-sm font-bold text-luxury-text">
                  {bankStatus.data?.bank_name ?? "Non communiqué"}
                </p>
              </div>
              <div className="rounded-2xl border border-slate-900/10 bg-white p-4 text-left shadow-sm">
                <div className="flex items-center gap-1.5 text-luxury-gold-deep">
                  <Clock className="h-3.5 w-3.5" />
                  <p className="text-xs font-medium text-luxury-text-light">Dernière synchro</p>
                </div>
                <p className="mt-1 truncate text-sm font-bold text-luxury-text">
                  {bankStatus.data?.last_sync_at ? formatDateTime(bankStatus.data.last_sync_at) : "Jamais encore"}
                </p>
              </div>
              <div className="rounded-2xl border border-slate-900/10 bg-white p-4 text-left shadow-sm">
                <div className="flex items-center gap-1.5 text-luxury-gold-deep">
                  <Receipt className="h-3.5 w-3.5" />
                  <p className="text-xs font-medium text-luxury-text-light">Transactions détectées</p>
                </div>
                <p className="mt-1 text-sm font-bold text-luxury-text">{bankStatus.data?.total_transactions ?? 0}</p>
              </div>
            </>
          )}
        </div>
      )}

      {user?.bank_connected ? (
        // Bouton secondaire, volontairement moins proéminent que le geste de
        // première connexion : la banque est déjà connectée, il ne reste
        // qu'une action de maintenance, pas un moment clé du parcours.
        <Button
          variant="outline"
          size="lg"
          className="mt-12"
          onClick={handleResync}
          loading={syncTransactions.isPending}
        >
          <RefreshCw className="h-4 w-4" /> Relancer une synchronisation
        </Button>
      ) : (
        <button
          ref={magneticRef}
          onClick={() => setShowAssurance(true)}
          disabled={bankConnectUrl.isPending}
          style={{ willChange: "transform" }}
          className="group relative mt-12 flex h-40 w-40 items-center justify-center rounded-full bg-luxury-night text-white shadow-[0_0_0_0_rgba(10,17,40,0)] transition-shadow duration-300 hover:shadow-[0_0_60px_10px_rgba(212,175,55,0.35)] disabled:opacity-60"
        >
          <span className="absolute inset-0 animate-ping rounded-full bg-luxury-gold/20" />
          <span className="relative flex flex-col items-center gap-1 text-sm font-semibold">
            {bankConnectUrl.isPending ? (
              "Connexion..."
            ) : (
              <>
                <Lock className="h-5 w-5 text-luxury-gold" />
                Connecter
                <ArrowRight className="h-4 w-4 text-luxury-gold" />
              </>
            )}
          </span>
        </button>
      )}

      <div className="mt-14 flex flex-col items-center gap-2 text-xs text-luxury-text-light">
        <p className="flex items-center gap-1.5">
          <ShieldCheck className="h-3.5 w-3.5" />
          Connexion chiffrée de bout en bout, via Powens (agréé DSP2)
        </p>
        <p className="flex items-center gap-1.5">
          <Lock className="h-3.5 w-3.5" />
          Tes identifiants bancaires ne transitent jamais par nos serveurs
        </p>
      </div>

      <BankSecurityAssuranceModal
        open={showAssurance}
        onOpenChange={setShowAssurance}
        onConfirm={() => {
          setShowAssurance(false);
          handleConnect();
        }}
        onLater={() => setShowAssurance(false)}
        connecting={bankConnectUrl.isPending}
      />
    </div>
  );
}
