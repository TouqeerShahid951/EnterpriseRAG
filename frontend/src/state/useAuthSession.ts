import { useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AUTH_SESSION_EXPIRED_EVENT } from "../api/client";
import { authApi } from "../api/contracts";

export function useAuthSession() {
  const queryClient = useQueryClient();
  const currentUserQuery = useQuery({
    queryKey: ["auth", "me"],
    queryFn: authApi.currentUser,
    retry: false,
  });

  const logoutMutation = useMutation({
    mutationFn: authApi.logout,
    onSettled: () => {
      queryClient.setQueryData(["auth", "me"], null);
      void queryClient.invalidateQueries({ queryKey: ["auth"] });
      void queryClient.invalidateQueries({ queryKey: ["admin"] });
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
    },
  });

  useEffect(() => {
    function handleSessionExpired() {
      queryClient.setQueryData(["auth", "me"], null);
      void queryClient.invalidateQueries({ queryKey: ["auth"] });
    }

    window.addEventListener(AUTH_SESSION_EXPIRED_EVENT, handleSessionExpired);
    return () => window.removeEventListener(AUTH_SESSION_EXPIRED_EVENT, handleSessionExpired);
  }, [queryClient]);

  function authChanged() {
    void queryClient.invalidateQueries({ queryKey: ["auth"] });
    void queryClient.invalidateQueries({ queryKey: ["admin"] });
    void queryClient.invalidateQueries({ queryKey: ["documents"] });
  }

  return {
    authChanged,
    currentUser: currentUserQuery.isSuccess ? currentUserQuery.data : null,
    currentUserQuery,
    logoutMutation,
  };
}
