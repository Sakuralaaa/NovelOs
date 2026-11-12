import { lazy, Suspense } from 'react'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { MutationCache, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Toaster, toast } from 'sonner'
import { TooltipProvider } from '@/components/ui/tooltip'
import { AppShell } from '@/components/layout/AppShell'
import { AuthGate } from '@/components/auth/AuthGate'
import { JobsProvider } from '@/lib/jobs'
import { useTheme } from '@/hooks/useTheme'
import { PageSkeleton } from '@/pages/_skeleton'

const Home = lazy(() => import('@/pages/Home'))
const RadarPage = lazy(() => import('@/pages/Radar'))
const Ideas = lazy(() => import('@/pages/Ideas'))
const IdeaDetail = lazy(() => import('@/pages/IdeaDetail'))
const Books = lazy(() => import('@/pages/Books'))
const BookOverview = lazy(() => import('@/pages/book/Overview'))
const Bible = lazy(() => import('@/pages/book/Bible'))
const StylePage = lazy(() => import('@/pages/book/Style'))
const Outline = lazy(() => import('@/pages/book/Outline'))
const Chapters = lazy(() => import('@/pages/book/Chapters'))
const Foreshadows = lazy(() => import('@/pages/book/Foreshadows'))
const PackagePage = lazy(() => import('@/pages/book/Package'))
const SettingsPage = lazy(() => import('@/pages/Settings'))
const NotFound = lazy(() => import('@/pages/NotFound'))

const qc = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 10_000, refetchOnWindowFocus: false, retry: (n, e: any) => (e?.status >= 400 && e?.status < 500 ? false : n < 1) },
    mutations: { retry: false },
  },
  mutationCache: new MutationCache({
    onError: (e: any, _v, _c, m) => {
      if (m.meta?.silent || e?.status === 401) return
      toast.error((m.meta?.errorTitle as string) || '操作失败', { description: e?.message })
    },
  }),
})

function ThemedToaster() {
  const t = useTheme()
  return <Toaster theme={t} position="top-center" richColors closeButton toastOptions={{ style: { fontFamily: 'inherit' } }} />
}

export function App() {
  return (
    <QueryClientProvider client={qc}>
      <TooltipProvider delayDuration={250}>
        <AuthGate>
        <JobsProvider>
          <BrowserRouter>
            <Routes>
              <Route element={<AppShell />}>
                <Route index element={<S><Home /></S>} />
                <Route path="radar" element={<S><RadarPage /></S>} />
                <Route path="ideas" element={<S><Ideas /></S>} />
                <Route path="ideas/:ideaId" element={<S><IdeaDetail /></S>} />
                <Route path="books" element={<S><Books /></S>} />
                <Route path="books/:bookId" element={<S><BookOverview /></S>} />
                <Route path="books/:bookId/bible" element={<S><Bible /></S>} />
                <Route path="books/:bookId/style" element={<S><StylePage /></S>} />
                <Route path="books/:bookId/outline" element={<S><Outline /></S>} />
                <Route path="books/:bookId/chapters" element={<S><Chapters /></S>} />
                <Route path="books/:bookId/chapters/:chapterId" element={<S><Chapters /></S>} />
                <Route path="books/:bookId/foreshadows" element={<S><Foreshadows /></S>} />
                <Route path="books/:bookId/package" element={<S><PackagePage /></S>} />
                <Route path="settings" element={<S><SettingsPage /></S>} />
                <Route path="*" element={<S><NotFound /></S>} />
              </Route>
            </Routes>
          </BrowserRouter>
        </JobsProvider>
        </AuthGate>
        <ThemedToaster />
      </TooltipProvider>
    </QueryClientProvider>
  )
}

function S({ children }: { children: React.ReactNode }) {
  return <Suspense fallback={<PageSkeleton />}>{children}</Suspense>
}
