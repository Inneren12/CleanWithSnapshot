"use client";

import Link from "next/link";

export type AdminNavLink = {
  label: string;
  href: string;
  key: string;
};

export default function AdminNav({ links, activeKey }: { links: AdminNavLink[]; activeKey?: string }) {
  if (!links.length) return null;
  return (
    <nav className="admin-nav" aria-label="Admin navigation">
      {links.map((link) => (
        <Link
          key={link.key}
          className={`admin-nav-link${activeKey === link.key ? " is-active" : ""}`}
          href={link.href}
        >
          {link.label}
        </Link>
      ))}
    </nav>
  );
}
