import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Connecting the Dots AI',
  description: 'Discover relationships between companies, markets, and opportunities',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}