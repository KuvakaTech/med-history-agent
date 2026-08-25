import { redirect } from "next/navigation";

export default function KioskSlugPage({
  params,
}: {
  params: { slug: string };
}) {
  redirect(`/kiosk/${params.slug}/start`);
}
