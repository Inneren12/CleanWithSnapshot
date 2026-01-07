import './globals.css';
import '../styles/design-system.css';
import type { Metadata } from 'next';
import { IBM_Plex_Sans } from 'next/font/google';

const ibmPlexSans = IBM_Plex_Sans({
  subsets: ['latin'],
  weight: ['400', '500', '600', '700'],
  variable: '--font-sans',
  display: 'swap'
});

export const metadata: Metadata = {
  title: 'Economy Cleaning — Edmonton',
  description: 'Honest, deterministic cleaning quotes in Edmonton.'
};

export default function RootLayout({
  children
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className={ibmPlexSans.variable}>
        {children}
      </body>
    </html>
  );
}
