interface Props { message: string }
export default function ErrorBox({ message }: Props) {
  return (
    <div className="bg-red-900/30 border border-red-700 text-red-300 rounded-lg px-4 py-3 text-sm">
      {message}
    </div>
  )
}
