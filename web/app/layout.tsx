import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Archive Workbench",
  description: "A local research workbench for historical documents.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
