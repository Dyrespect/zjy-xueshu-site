import { useNavigate, useSearchParams } from "react-router";

import { LoginForm } from "@/blocks/admin-login";
import { adminLogin } from "@/lib/admin";

export function AdminLoginPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const next = params.get("next");
  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <LoginForm
        onSubmit={async (password) => {
          await adminLogin(password);
          navigate(next && next.startsWith("/admin") ? next : "/admin/conversations", { replace: true });
        }}
      />
    </div>
  );
}
