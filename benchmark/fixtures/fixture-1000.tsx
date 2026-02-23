import {
  useState,
  useEffect,
  useCallback,
  useMemo,
  useRef,
  useReducer,
  createContext,
  useContext,
} from "react";
import type { ReactNode, FormEvent } from "react";

// Types & Interfaces
interface User {
  id: string;
  name: string;
  email: string;
  role: "admin" | "editor" | "viewer";
  department: string;
  lastLoginAt: Date | null;
  createdAt: Date;
  isActive: boolean;
}

interface AnalyticsData {
  pageViews: TimeSeriesPoint[];
  visitors: TimeSeriesPoint[];
  bounceRate: TimeSeriesPoint[];
}

interface TimeSeriesPoint {
  timestamp: string;
  value: number;
}

interface DateRange {
  start: Date;
  end: Date;
  preset: "today" | "7d" | "30d" | "90d" | null;
}

interface ApiResponse<T> {
  data: T;
  meta: { total: number; page: number };
  error: string | null;
}

// Constants
const API_BASE = "/api/v2";
const PAGE_SIZE = 25;
const DEBOUNCE_MS = 300;
const POLL_MS = 30_000;
const ROLE_LABELS: Record<string, string> = {
  admin: "Administrator",
  editor: "Editor",
  viewer: "Viewer",
};

const ROLE_COLORS: Record<string, string> = {
  admin: "bg-red-100 text-red-800",
  editor: "bg-blue-100 text-blue-800",
  viewer: "bg-gray-100 text-gray-800",
};

const DEPARTMENTS = [
  "Engineering",
  "Marketing",
  "Sales",
  "Product",
  "Design",
  "Support",
] as const;

// Context
interface DashboardCtx {
  dateRange: DateRange;
  setDateRange: (r: DateRange) => void;
  refreshData: () => void;
}

const DashboardContext = createContext<DashboardCtx | null>(null);

function useDashboard(): DashboardCtx {
  const ctx = useContext(DashboardContext);
  if (!ctx) {
    throw new Error("useDashboard must be within provider");
  }
  return ctx;
}

// Reducer
type Action =
  | { type: "SET_LOADING"; payload: boolean }
  | { type: "SET_ANALYTICS"; payload: AnalyticsData }
  | { type: "SET_USERS"; payload: { users: User[]; total: number } }
  | { type: "SET_ERROR"; payload: string }
  | { type: "CLEAR_ERROR" }
  | { type: "SET_PAGE"; payload: number }
  | { type: "SET_SEARCH"; payload: string }
  | { type: "SET_ROLE_FILTER"; payload: string }
  | { type: "SET_SORT"; payload: { field: string; order: "asc" | "desc" } }
  | { type: "TOGGLE_SELECT"; payload: string }
  | { type: "CLEAR_SELECT" }
  | { type: "OPEN_EDIT"; payload: User }
  | { type: "CLOSE_EDIT" }
  | { type: "OPEN_DELETE"; payload: string | null }
  | { type: "CLOSE_DELETE" }
  | { type: "SET_REFRESH_TS"; payload: number };

interface State {
  loading: boolean;
  error: string | null;
  analytics: AnalyticsData | null;
  users: User[];
  totalUsers: number;
  page: number;
  search: string;
  roleFilter: string;
  sortField: string;
  sortOrder: "asc" | "desc";
  selected: Set<string>;
  editingUser: User | null;
  deleteTargetId: string | null;
  showDeleteModal: boolean;
  refreshTs: number;
}

const initState: State = {
  loading: true,
  error: null,
  analytics: null,
  users: [],
  totalUsers: 0,
  page: 1,
  search: "",
  roleFilter: "",
  sortField: "name",
  sortOrder: "asc",
  selected: new Set(),
  editingUser: null,
  deleteTargetId: null,
  showDeleteModal: false,
  refreshTs: 0,
};

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case "SET_LOADING":
      return { ...state, loading: action.payload };
    case "SET_ANALYTICS":
      return { ...state, analytics: action.payload, loading: false };
    case "SET_USERS":
      return {
        ...state,
        users: action.payload.users,
        totalUsers: action.payload.total,
      };
    case "SET_ERROR":
      return { ...state, error: action.payload, loading: false };
    case "CLEAR_ERROR":
      return { ...state, error: null };
    case "SET_PAGE":
      return { ...state, page: action.payload };
    case "SET_SEARCH":
      return { ...state, search: action.payload, page: 1 };
    case "SET_ROLE_FILTER":
      return { ...state, roleFilter: action.payload, page: 1 };
    case "SET_SORT":
      return {
        ...state,
        sortField: action.payload.field,
        sortOrder: action.payload.order,
      };
    case "TOGGLE_SELECT": {
      const next = new Set(state.selected);
      if (next.has(action.payload)) next.delete(action.payload);
      else next.add(action.payload);
      return { ...state, selected: next };
    }
    case "CLEAR_SELECT":
      return { ...state, selected: new Set() };
    case "OPEN_EDIT":
      return { ...state, editingUser: action.payload };
    case "CLOSE_EDIT":
      return { ...state, editingUser: null };
    case "OPEN_DELETE":
      return {
        ...state,
        showDeleteModal: true,
        deleteTargetId: action.payload,
      };
    case "CLOSE_DELETE":
      return {
        ...state,
        showDeleteModal: false,
        deleteTargetId: null,
      };
    case "SET_REFRESH_TS":
      return { ...state, refreshTs: action.payload };
    default:
      return state;
  }
}

// API Functions
async function fetchAnalytics(range: DateRange): Promise<AnalyticsData> {
  const params = new URLSearchParams({
    start: range.start.toISOString(),
    end: range.end.toISOString(),
  });
  const res = await fetch(`${API_BASE}/analytics?${params}`);
  if (!res.ok) {
    throw new Error(`Analytics fetch failed: ${res.statusText}`);
  }
  const json: ApiResponse<AnalyticsData> = await res.json();
  if (json.error) throw new Error(json.error);
  return json.data;
}

async function fetchUsers(p: {
  page: number;
  search: string;
  role: string;
  sort: string;
  order: string;
}): Promise<ApiResponse<User[]>> {
  const q = new URLSearchParams({
    page: String(p.page),
    per_page: String(PAGE_SIZE),
    sort: p.sort,
    order: p.order,
  });
  if (p.search) q.set("q", p.search);
  if (p.role) q.set("role", p.role);
  const res = await fetch(`${API_BASE}/users?${q}`);
  if (!res.ok) {
    throw new Error(`Users fetch failed: ${res.statusText}`);
  }
  return res.json();
}

async function updateUser(id: string, data: Partial<User>): Promise<User> {
  const res = await fetch(`${API_BASE}/users/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => null);
    throw new Error(err?.error || `Update failed`);
  }
  return (await res.json()).data;
}

async function deleteUsers(ids: string[]): Promise<void> {
  const res = await fetch(`${API_BASE}/users/batch-delete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ids }),
  });
  if (!res.ok) {
    throw new Error(`Delete failed: ${res.statusText}`);
  }
}

// Utility Functions
function fmtNum(v: number): string {
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `${(v / 1_000).toFixed(1)}K`;
  return v.toLocaleString();
}

function fmtDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return m === 0 ? `${s}s` : `${m}m ${s}s`;
}

function fmtPct(v: number): string {
  return `${(v * 100).toFixed(1)}%`;
}

function fmtRelative(d: Date | string): string {
  const ms = Date.now() - new Date(d).getTime();
  const mins = Math.floor(ms / 60_000);
  if (mins < 1) return "Just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(ms / 3_600_000);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(ms / 86_400_000)}d ago`;
}

function cx(...classes: (string | false | null | undefined)[]): string {
  return classes.filter(Boolean).join(" ");
}

function getPresetRange(preset: string): DateRange {
  const end = new Date();
  const start = new Date();
  if (preset === "today") start.setHours(0, 0, 0, 0);
  else if (preset === "7d") start.setDate(start.getDate() - 7);
  else if (preset === "30d") start.setDate(start.getDate() - 30);
  else if (preset === "90d") start.setDate(start.getDate() - 90);
  else start.setDate(start.getDate() - 30);
  return { start, end, preset: preset as DateRange["preset"] };
}

// Error Boundary
class ErrorBoundary extends React.Component<
  { children: ReactNode },
  { hasError: boolean; error: Error | null }
> {
  constructor(props: { children: ReactNode }) {
    super(props);
    this.state = { hasError: false, error: null };
  }
  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error };
  }
  render() {
    if (this.state.hasError) {
      return (
        <div className="flex flex-col items-center p-8">
          <p className="text-red-500 font-semibold mb-2">
            Something went wrong
          </p>
          <p className="text-gray-600 text-sm mb-4">
            {this.state.error?.message}
          </p>
          <button
            onClick={() => this.setState({ hasError: false, error: null })}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg"
          >
            Retry
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

// Sub-Components
function MetricCard({
  title,
  value,
  change,
  fmt = "number",
}: {
  title: string;
  value: number;
  change: number;
  fmt?: "number" | "duration" | "pct";
}) {
  const display = useMemo(() => {
    if (fmt === "duration") return fmtDuration(value);
    if (fmt === "pct") return fmtPct(value);
    return fmtNum(value);
  }, [value, fmt]);
  const positive = change >= 0;
  return (
    <div className="bg-white rounded-xl shadow-sm border p-6">
      <div className="text-sm text-gray-500 mb-1">{title}</div>
      <div className="text-3xl font-bold text-gray-900 mb-2">{display}</div>
      <div
        className={cx(
          "text-sm font-medium",
          positive ? "text-green-600" : "text-red-600",
        )}
      >
        {positive ? "\u2191" : "\u2193"} {Math.abs(change).toFixed(1)}%
      </div>
    </div>
  );
}

function DateRangePicker({
  value,
  onChange,
}: {
  value: DateRange;
  onChange: (r: DateRange) => void;
}) {
  const presets = [
    { label: "Today", v: "today" },
    { label: "7D", v: "7d" },
    { label: "30D", v: "30d" },
    { label: "90D", v: "90d" },
  ];
  return (
    <div className="flex gap-2">
      {presets.map((p) => (
        <button
          key={p.v}
          onClick={() => onChange(getPresetRange(p.v))}
          className={cx(
            "px-3 py-1.5 text-sm rounded-lg",
            value.preset === p.v
              ? "bg-blue-600 text-white"
              : "bg-gray-100 text-gray-700 hover:bg-gray-200",
          )}
        >
          {p.label}
        </button>
      ))}
    </div>
  );
}

function UserTable({
  users,
  selected,
  sortField,
  sortOrder,
  onSort,
  onToggle,
  onSelectAll,
  onEdit,
  onDelete,
}: {
  users: User[];
  selected: Set<string>;
  sortField: string;
  sortOrder: "asc" | "desc";
  onSort: (f: string) => void;
  onToggle: (id: string) => void;
  onSelectAll: () => void;
  onEdit: (u: User) => void;
  onDelete: (id: string) => void;
}) {
  const allSelected =
    users.length > 0 && users.every((u) => selected.has(u.id));
  const cols = [
    { key: "name", label: "Name", sortable: true },
    { key: "email", label: "Email", sortable: true },
    { key: "role", label: "Role", sortable: true },
    { key: "department", label: "Dept", sortable: true },
    { key: "lastLoginAt", label: "Last Login", sortable: true },
  ];
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full divide-y divide-gray-200">
        <thead className="bg-gray-50">
          <tr>
            <th className="px-4 py-3 w-10">
              <input
                type="checkbox"
                checked={allSelected}
                onChange={onSelectAll}
                className="rounded border-gray-300"
              />
            </th>
            {cols.map((c) => (
              <th
                key={c.key}
                onClick={() => c.sortable && onSort(c.key)}
                className={cx(
                  "px-4 py-3 text-left text-xs",
                  "font-semibold text-gray-500 uppercase",
                  c.sortable && "cursor-pointer",
                )}
              >
                {c.label}
                {sortField === c.key && (
                  <span className="ml-1 text-blue-600">
                    {sortOrder === "asc" ? "\u25B2" : "\u25BC"}
                  </span>
                )}
              </th>
            ))}
            <th className="px-4 py-3 text-right text-xs">Actions</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-200">
          {users.map((user) => (
            <tr
              key={user.id}
              className={cx(
                "hover:bg-gray-50",
                selected.has(user.id) && "bg-blue-50",
              )}
            >
              <td className="px-4 py-3">
                <input
                  type="checkbox"
                  checked={selected.has(user.id)}
                  onChange={() => onToggle(user.id)}
                  className="rounded border-gray-300"
                />
              </td>
              <td className="px-4 py-3">
                <div className="flex items-center gap-3">
                  <div className="w-8 h-8 rounded-full bg-gray-200 flex items-center justify-center text-sm">
                    {user.name[0]}
                  </div>
                  <span className="text-sm font-medium">{user.name}</span>
                </div>
              </td>
              <td className="px-4 py-3 text-sm text-gray-600">{user.email}</td>
              <td className="px-4 py-3">
                <span
                  className={cx(
                    "px-2.5 py-0.5 rounded-full text-xs",
                    ROLE_COLORS[user.role],
                  )}
                >
                  {ROLE_LABELS[user.role]}
                </span>
              </td>
              <td className="px-4 py-3 text-sm text-gray-600">
                {user.department}
              </td>
              <td className="px-4 py-3 text-sm text-gray-500">
                {user.lastLoginAt ? fmtRelative(user.lastLoginAt) : "Never"}
              </td>
              <td className="px-4 py-3 text-right space-x-2">
                <button
                  onClick={() => onEdit(user)}
                  className="text-gray-400 hover:text-blue-600"
                >
                  Edit
                </button>
                <button
                  onClick={() => onDelete(user.id)}
                  className="text-gray-400 hover:text-red-600"
                >
                  Delete
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {users.length === 0 && (
        <div className="text-center py-12 text-gray-500">No users found.</div>
      )}
    </div>
  );
}

function SimplePagination({
  page,
  total,
  onChange,
}: {
  page: number;
  total: number;
  onChange: (p: number) => void;
}) {
  return (
    <div className="flex items-center justify-between px-4 py-3 border-t">
      <button
        disabled={page <= 1}
        onClick={() => onChange(page - 1)}
        className="px-3 py-1.5 text-sm border rounded-lg disabled:opacity-50"
      >
        Previous
      </button>
      <span className="text-sm text-gray-600">
        Page {page} of {total}
      </span>
      <button
        disabled={page >= total}
        onClick={() => onChange(page + 1)}
        className="px-3 py-1.5 text-sm border rounded-lg disabled:opacity-50"
      >
        Next
      </button>
    </div>
  );
}

function UserEditModal({
  user,
  onClose,
  onSave,
}: {
  user: User;
  onClose: () => void;
  onSave: (d: Partial<User>) => Promise<void>;
}) {
  const [form, setForm] = useState({
    name: user.name,
    email: user.email,
    role: user.role,
    department: user.department,
    isActive: user.isActive,
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await onSave(form);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-white rounded-2xl shadow-xl max-w-lg w-full mx-4">
        <div className="flex justify-between px-6 py-4 border-b">
          <h2 className="text-lg font-semibold">Edit User</h2>
          <button onClick={onClose} className="text-gray-400">
            X
          </button>
        </div>
        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {error && (
            <div className="p-3 bg-red-50 border-red-200 border rounded text-sm text-red-700">
              {error}
            </div>
          )}
          <div>
            <label className="block text-sm font-medium mb-1">Name</label>
            <input
              type="text"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              className="w-full px-3 py-2 border rounded-lg"
              required
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">Email</label>
            <input
              type="email"
              value={form.email}
              onChange={(e) => setForm({ ...form, email: e.target.value })}
              className="w-full px-3 py-2 border rounded-lg"
              required
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">Role</label>
            <select
              value={form.role}
              onChange={(e) =>
                setForm({
                  ...form,
                  role: e.target.value as User["role"],
                })
              }
              className="w-full px-3 py-2 border rounded-lg"
            >
              {Object.entries(ROLE_LABELS).map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </select>
          </div>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={form.isActive}
              onChange={(e) =>
                setForm({
                  ...form,
                  isActive: e.target.checked,
                })
              }
              className="rounded border-gray-300"
            />
            <span className="text-sm">Active</span>
          </label>
          <div className="flex justify-end gap-3 pt-4 border-t">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm bg-gray-100 rounded-lg"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={saving}
              className="px-4 py-2 text-sm text-white bg-blue-600 rounded-lg disabled:opacity-50"
            >
              {saving ? "Saving..." : "Save"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function ConfirmModal({
  count,
  onClose,
  onConfirm,
}: {
  count: number;
  onClose: () => void;
  onConfirm: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-white rounded-2xl shadow-xl max-w-sm w-full mx-4 p-6">
        <h3 className="text-lg font-semibold mb-2">Confirm Deletion</h3>
        <p className="text-sm text-gray-600 mb-6">
          Delete {count} {count === 1 ? "user" : "users"} and all associated
          data? This cannot be undone.
        </p>
        <div className="flex justify-end gap-3">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm bg-gray-100 rounded-lg"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            className="px-4 py-2 text-sm text-white bg-red-600 rounded-lg"
          >
            Delete
          </button>
        </div>
      </div>
    </div>
  );
}

// Main Component
export default function AnalyticsDashboard() {
  const [state, dispatch] = useReducer(reducer, initState);
  const [dateRange, setDateRange] = useState<DateRange>(getPresetRange("30d"));
  const [isPolling, setIsPolling] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const totalPages = Math.ceil(state.totalUsers / PAGE_SIZE);

  const loadAnalytics = useCallback(async () => {
    try {
      const data = await fetchAnalytics(dateRange);
      dispatch({ type: "SET_ANALYTICS", payload: data });
      dispatch({
        type: "SET_REFRESH_TS",
        payload: Date.now(),
      });
    } catch (err) {
      dispatch({
        type: "SET_ERROR",
        payload: err instanceof Error ? err.message : "Analytics load failed",
      });
    }
  }, [dateRange]);

  const loadUsers = useCallback(async () => {
    try {
      const res = await fetchUsers({
        page: state.page,
        search: state.search,
        role: state.roleFilter,
        sort: state.sortField,
        order: state.sortOrder,
      });
      dispatch({
        type: "SET_USERS",
        payload: {
          users: res.data,
          total: res.meta.total,
        },
      });
    } catch (err) {
      dispatch({
        type: "SET_ERROR",
        payload: err instanceof Error ? err.message : "Users load failed",
      });
    }
  }, [
    state.page,
    state.search,
    state.roleFilter,
    state.sortField,
    state.sortOrder,
  ]);

  const refreshData = useCallback(() => {
    dispatch({ type: "SET_LOADING", payload: true });
    Promise.all([loadAnalytics(), loadUsers()]).finally(() =>
      dispatch({ type: "SET_LOADING", payload: false }),
    );
  }, [loadAnalytics, loadUsers]);

  useEffect(() => {
    refreshData();
  }, [refreshData]);

  useEffect(() => {
    if (isPolling) {
      pollRef.current = setInterval(refreshData, POLL_MS);
    } else if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [isPolling, refreshData]);

  const debouncedSearch = useMemo(() => {
    let timer: ReturnType<typeof setTimeout> | null = null;
    return (val: string) => {
      if (timer) clearTimeout(timer);
      timer = setTimeout(
        () => dispatch({ type: "SET_SEARCH", payload: val }),
        DEBOUNCE_MS,
      );
    };
  }, []);

  const handleSort = useCallback(
    (field: string) => {
      const order =
        state.sortField === field && state.sortOrder === "asc" ? "desc" : "asc";
      dispatch({
        type: "SET_SORT",
        payload: { field, order },
      });
    },
    [state.sortField, state.sortOrder],
  );

  const handleSelectAll = useCallback(() => {
    if (state.users.every((u) => state.selected.has(u.id))) {
      dispatch({ type: "CLEAR_SELECT" });
    } else {
      dispatch({
        type: "TOGGLE_SELECT",
        payload: state.users[0]?.id ?? "",
      });
    }
  }, [state.users, state.selected]);

  const handleSaveUser = useCallback(
    async (data: Partial<User>) => {
      if (!state.editingUser) return;
      await updateUser(state.editingUser.id, data);
      await loadUsers();
    },
    [state.editingUser, loadUsers],
  );

  const handleConfirmDelete = useCallback(async () => {
    const tid = state.deleteTargetId;
    const ids = tid ? [tid] : Array.from(state.selected);
    if (!ids.length) return;
    try {
      await deleteUsers(ids);
      dispatch({ type: "CLEAR_SELECT" });
      dispatch({ type: "CLOSE_DELETE" });
      await loadUsers();
    } catch (err) {
      dispatch({
        type: "SET_ERROR",
        payload: err instanceof Error ? err.message : "Delete failed",
      });
    }
  }, [state.deleteTargetId, state.selected, loadUsers]);

  const ctxValue = useMemo<DashboardCtx>(
    () => ({ dateRange, setDateRange, refreshData }),
    [dateRange, refreshData],
  );

  return (
    <DashboardContext.Provider value={ctxValue}>
      <ErrorBoundary>
        <div className="min-h-screen bg-gray-50">
          <header className="bg-white border-b sticky top-0 z-30">
            <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
              <div className="flex items-center justify-between h-16">
                <h1 className="text-xl font-bold">Analytics Dashboard</h1>
                <div className="flex items-center gap-3">
                  <DateRangePicker value={dateRange} onChange={setDateRange} />
                  <button
                    onClick={() => setIsPolling((p) => !p)}
                    className={cx(
                      "px-3 py-1.5 text-sm rounded-lg",
                      isPolling
                        ? "bg-green-100 text-green-700"
                        : "bg-gray-100 text-gray-600",
                    )}
                  >
                    {isPolling ? "Live" : "Paused"}
                  </button>
                  <button
                    onClick={refreshData}
                    disabled={state.loading}
                    className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded-lg disabled:opacity-50"
                  >
                    Refresh
                  </button>
                </div>
              </div>
            </div>
          </header>

          <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
            {state.error && (
              <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-xl flex justify-between">
                <span className="text-sm text-red-700">{state.error}</span>
                <button
                  onClick={() => dispatch({ type: "CLEAR_ERROR" })}
                  className="text-red-400 hover:text-red-600"
                >
                  Dismiss
                </button>
              </div>
            )}

            {state.analytics && (
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
                <MetricCard
                  title="Page Views"
                  value={state.analytics.pageViews.reduce(
                    (s, p) => s + p.value,
                    0,
                  )}
                  change={12.5}
                />
                <MetricCard
                  title="Unique Visitors"
                  value={state.analytics.visitors.reduce(
                    (s, p) => s + p.value,
                    0,
                  )}
                  change={8.2}
                />
                <MetricCard
                  title="Bounce Rate"
                  value={state.analytics.bounceRate.at(-1)?.value ?? 0}
                  change={-3.1}
                  fmt="pct"
                />
                <MetricCard
                  title="Avg Session"
                  value={245}
                  change={5.7}
                  fmt="duration"
                />
              </div>
            )}

            <div className="bg-white rounded-xl shadow-sm border">
              <div className="px-6 py-4 border-b">
                <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
                  <div className="flex items-center gap-4">
                    <h2 className="text-lg font-semibold">Users</h2>
                    <span className="text-sm text-gray-500">
                      {state.totalUsers} total
                    </span>
                  </div>
                  <div className="flex items-center gap-3">
                    <input
                      ref={searchRef}
                      type="text"
                      placeholder="Search..."
                      onChange={(e) => debouncedSearch(e.target.value)}
                      className="px-3 py-1.5 text-sm border rounded-lg w-48"
                    />
                    <select
                      value={state.roleFilter}
                      onChange={(e) =>
                        dispatch({
                          type: "SET_ROLE_FILTER",
                          payload: e.target.value,
                        })
                      }
                      className="px-3 py-1.5 text-sm border rounded-lg"
                    >
                      <option value="">All Roles</option>
                      {Object.entries(ROLE_LABELS).map(([v, l]) => (
                        <option key={v} value={v}>
                          {l}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>
              </div>

              <UserTable
                users={state.users}
                selected={state.selected}
                sortField={state.sortField}
                sortOrder={state.sortOrder}
                onSort={handleSort}
                onToggle={(id) =>
                  dispatch({
                    type: "TOGGLE_SELECT",
                    payload: id,
                  })
                }
                onSelectAll={handleSelectAll}
                onEdit={(u) =>
                  dispatch({
                    type: "OPEN_EDIT",
                    payload: u,
                  })
                }
                onDelete={(id) =>
                  dispatch({
                    type: "OPEN_DELETE",
                    payload: id,
                  })
                }
              />

              {totalPages > 1 && (
                <SimplePagination
                  page={state.page}
                  total={totalPages}
                  onChange={(p) =>
                    dispatch({
                      type: "SET_PAGE",
                      payload: p,
                    })
                  }
                />
              )}
            </div>
          </main>

          {state.editingUser && (
            <UserEditModal
              user={state.editingUser}
              onClose={() => dispatch({ type: "CLOSE_EDIT" })}
              onSave={handleSaveUser}
            />
          )}

          {state.showDeleteModal && (
            <ConfirmModal
              count={state.deleteTargetId ? 1 : state.selected.size}
              onClose={() => dispatch({ type: "CLOSE_DELETE" })}
              onConfirm={handleConfirmDelete}
            />
          )}
        </div>
      </ErrorBoundary>
    </DashboardContext.Provider>
  );
}
