import type { Metadata } from "next";
import { ThemeProvider } from "next-themes";
import "./globals.css";
export const metadata: Metadata = {
  title: "Automated Apply · Your next chapter",
  description: "Your private job-search command center",
  robots: { index: false, follow: false },
};
export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>
        <ThemeProvider
          attribute="class"
          defaultTheme="system"
          enableSystem
          disableTransitionOnChange
        >
          {children}
        </ThemeProvider>
      </body>
    </html>
  );
}
