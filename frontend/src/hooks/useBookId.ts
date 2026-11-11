import { useParams } from 'react-router-dom'
export function useBookId() {
  const { bookId } = useParams()
  return Number(bookId) || 0
}
