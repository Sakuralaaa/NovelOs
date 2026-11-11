import { useQuery } from '@tanstack/react-query'
import { api, qk } from '@/lib/api'

export const useStatus = () => useQuery({ queryKey: qk.status, queryFn: api.status, staleTime: 30_000 })
export const useChannels = () => useQuery({ queryKey: qk.channels, queryFn: api.channels })
export const useBooks = () => useQuery({ queryKey: qk.books, queryFn: api.books })
export const useBook = (id: number) => useQuery({ queryKey: qk.book(id), queryFn: () => api.book(id), enabled: !!id })
export const useJobsList = (bookId?: number) =>
  useQuery({ queryKey: qk.jobs(bookId), queryFn: () => api.jobs(bookId), refetchInterval: 5000 })
