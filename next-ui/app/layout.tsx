import "./globals.css";
import type { ReactNode } from "react";

export const metadata = {
  title: "ForgeFlow Dashboard",
  description: "ForgeFlow email processing dashboard"
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
