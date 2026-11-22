import { cookies, headers } from "next/headers";
import { redirect } from "next/navigation";
import { SESSION_COOKIE, validSession, configuration } from "@/lib/security";
import { Providers } from "@/components/providers";
import { Shell } from "@/components/shell";
export const dynamic = "force-dynamic";
export default async function Workspace({
  children,
}: {
  children: React.ReactNode;
}) {
  const session = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!validSession(session)) redirect("/login");
  const config = configuration();
  if ((await headers()).get("host") !== new URL(config.origin).host)
    redirect("/login");
  return (
    <Providers>
      <Shell>{children}</Shell>
    </Providers>
  );
}
