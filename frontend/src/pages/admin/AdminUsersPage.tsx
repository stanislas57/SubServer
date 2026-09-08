import * as React from "react";
import { Search, ChevronLeft, ChevronRight } from "lucide-react";
import { AdminUsersTable } from "@/components/admin/AdminUsersTable";
import { AdminUserEditDrawer } from "@/components/admin/AdminUserEditDrawer";
import { useAdminUsers } from "@/hooks/useAdmin";

/** Vue "Gestion des Utilisateurs" : recherche + tableau paginé + panneau
 * d'édition (Drawer) déclenché par ligne. */
export function AdminUsersPage() {
  const [search, setSearch] = React.useState("");
  // Débouncé séparément de `search` : sans ça, chaque frappe change la
  // queryKey de useAdminUsers et tire une requête GET /admin/users --
  // l'input reste réactif sur `search`, seule la requête attend une pause de
  // frappe de 300ms sur `debouncedSearch`.
  const [debouncedSearch, setDebouncedSearch] = React.useState("");
  const [page, setPage] = React.useState(1);
  const [editingUserId, setEditingUserId] = React.useState<string | null>(null);

  React.useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(search), 300);
    return () => clearTimeout(timer);
  }, [search]);

  const usersQuery = useAdminUsers({ q: debouncedSearch, page, pageSize: 20 });
  // Dérivé de la requête (jamais un instantané figé) : si une mutation dans
  // le drawer invalide la liste (ex: bascule Premium), l'utilisateur affiché
  // ici se met à jour automatiquement dès le refetch, sans état dupliqué.
  const editingUser = usersQuery.data?.items.find((u) => u.id === editingUserId) ?? null;
  const totalPages = usersQuery.data ? Math.max(1, Math.ceil(usersQuery.data.total / usersQuery.data.page_size)) : 1;

  function handleSearchChange(value: string) {
    setSearch(value);
    setPage(1);
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-bold text-slate-100">Gestion des utilisateurs</h1>
        <p className="text-sm text-slate-500">
          {usersQuery.data ? `${usersQuery.data.total} compte(s) au total` : "Chargement…"}
        </p>
      </div>

      <div className="relative max-w-sm">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
        <input
          value={search}
          onChange={(e) => handleSearchChange(e.target.value)}
          placeholder="Rechercher par email ou prénom…"
          className="w-full rounded-md border border-slate-700 bg-slate-900 py-2 pl-9 pr-3 text-sm text-slate-100 placeholder:text-slate-500 focus:border-amber-500 focus:outline-none"
        />
      </div>

      <AdminUsersTable
        users={usersQuery.data?.items ?? []}
        isLoading={usersQuery.isPending}
        onEdit={(user) => setEditingUserId(user.id)}
      />

      {usersQuery.data && usersQuery.data.total > usersQuery.data.page_size && (
        <div className="flex items-center justify-between text-sm text-slate-400">
          <span>
            Page {usersQuery.data.page} / {totalPages}
          </span>
          <div className="flex gap-2">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1}
              className="flex items-center gap-1 rounded-md border border-slate-700 bg-slate-900 px-3 py-1.5 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <ChevronLeft className="h-3.5 w-3.5" /> Précédent
            </button>
            <button
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages}
              className="flex items-center gap-1 rounded-md border border-slate-700 bg-slate-900 px-3 py-1.5 disabled:cursor-not-allowed disabled:opacity-40"
            >
              Suivant <ChevronRight className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      )}

      <AdminUserEditDrawer user={editingUser} onOpenChange={(open) => !open && setEditingUserId(null)} />
    </div>
  );
}
