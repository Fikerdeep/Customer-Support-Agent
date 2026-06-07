import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "Loopp Refund Agent",
  description: "AI customer-support agent for e-commerce refunds",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <nav className="nav">
          <div className="brand">
            Loopp<span>·</span>Assist
          </div>
          <Link className="link" href="/">
            Customer Chat
          </Link>
          <Link className="link" href="/admin">
            Admin Dashboard
          </Link>
        </nav>
        {children}
      </body>
    </html>
  );
}
