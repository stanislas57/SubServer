import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { bankService } from "@/services/bankService";
import type { BankCallbackInput } from "@/types";

export function useBankProviders() {
  return useQuery({ queryKey: ["bank", "providers"], queryFn: bankService.listProviders });
}

export function useBankSync() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (providerId: string) => bankService.sync(providerId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["subscriptions"] });
      queryClient.invalidateQueries({ queryKey: ["me"] });
    },
  });
}

/** Étape 1 du flow réel Powens : récupère l'URL de la Webview à ouvrir. */
export function useBankConnectUrl() {
  return useMutation({ mutationFn: bankService.getConnectUrl });
}

/** Étape 2 du flow réel Powens : à appeler avec les query params reçus au retour de la Webview. */
export function useBankCallback() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: BankCallbackInput) => bankService.handleCallback(input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["subscriptions"] });
      queryClient.invalidateQueries({ queryKey: ["me"] });
      queryClient.invalidateQueries({ queryKey: ["bank", "status"] });
    },
  });
}

/** Récupère les transactions brutes depuis Powens et les stocke. */
export function useSyncTransactions() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: bankService.syncTransactions,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["bank", "status"] });
    },
  });
}

/** Lance l'algorithme de détection sur les transactions déjà stockées. */
export function useDetectSubscriptions() {
  return useMutation({ mutationFn: bankService.detectSubscriptions });
}

/** Indicateurs de réassurance page Banque : établissement, dernière synchro, volume.
 * `enabled` par défaut à true pour ne rien casser côté appelants existants,
 * mais BankConnectPage le passe à false tant qu'aucune banque n'est
 * connectée (l'UI qui consomme ces données ne s'affiche de toute façon pas
 * avant ça) pour éviter un GET /bank/status inutile à chaque visite. */
export function useBankStatus(enabled = true) {
  return useQuery({ queryKey: ["bank", "status"], queryFn: bankService.getStatus, enabled });
}
