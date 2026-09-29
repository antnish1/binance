import type { Metadata } from "next";
import "./globals.css";
import "./compact.css";

export const metadata: Metadata = {
  title: "Taddy Control Center",
  description: "Paper market automation, risk, replay and system observability",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
