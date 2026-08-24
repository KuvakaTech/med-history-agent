import { redirect } from "next/navigation";

// /checkin/:slug → /checkin/:slug/start
export default function CheckinRoot({ params }: { params: { slug: string } }) {
  redirect(`/checkin/${params.slug}/start`);
}
