interface ReviewBadgeProps {
  seq: number
  difficulty?: number
}

/** 复习点徽标：🔁 第 N 次（难度 ≥4 时附注「难度高」） */
export function ReviewBadge({ seq, difficulty }: ReviewBadgeProps) {
  return (
    <span className="badge badge--review" title={`第 ${seq} 次复习`}>
      🔁 第 {seq} 次复习
      {difficulty !== undefined && difficulty >= 4 && (
        <span className="badge__note">难度高</span>
      )}
    </span>
  )
}
