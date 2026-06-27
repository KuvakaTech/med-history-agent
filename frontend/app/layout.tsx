import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "kuvaka Clinical AI",
  description: "Intelligent clinical history-taking assistant",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
