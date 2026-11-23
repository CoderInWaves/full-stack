interface Props { message: string; onConfirm: () => void; onCancel: () => void }

export default function ConfirmDialog({ message, onConfirm, onCancel }: Props) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-gray-900 border border-gray-700 rounded-xl p-6 w-80 shadow-2xl">
        <p className="text-white mb-5 text-sm">{message}</p>
        <div className="flex gap-3 justify-end">
          <button onClick={onCancel}
            className="px-4 py-2 text-sm rounded-lg bg-gray-800 text-gray-300 hover:bg-gray-700">
            Cancel
          </button>
          <button onClick={onConfirm}
            className="px-4 py-2 text-sm rounded-lg bg-red-600 text-white hover:bg-red-700">
            Confirm
          </button>
        </div>
      </div>
    </div>
  )
}
