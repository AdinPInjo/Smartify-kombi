import { useEffect, type ReactNode } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { setUnauthorizedHandler } from "@/api/client";
import { useMe } from "@/api/hooks";
import { Skeleton } from "@/components/ui";

/** Wraps every page that needs a login; sends the user to /login on any 401. */
export function RequireLogin({ children }: { children: ReactNode }) {
  const me = useMe();
  const location = useLocation();
  const navigate = useNavigate();
  const client = useQueryClient();

  useEffect(() => {
    setUnauthorizedHandler(() => {
      client.clear();
      navigate("/login", { replace: true, state: { from: location.pathname } });
    });
  }, [client, navigate, location.pathname]);

  if (me.isPending) {
    return (
      <div className="page">
        <Skeleton height={40} width={200} />
        <Skeleton height={240} />
      </div>
    );
  }
  if (me.isError) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return <>{children}</>;
}
