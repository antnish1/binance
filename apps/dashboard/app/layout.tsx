import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Binance Fast Bot",
  description: "Read-only trading engine control plane",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
