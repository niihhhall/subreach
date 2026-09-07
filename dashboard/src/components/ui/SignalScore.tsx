import React from 'react'

interface SignalScoreProps {
    score: number
    label?: string
    size?: 'sm' | 'md' | 'lg'
}

export const SignalScore: React.FC<SignalScoreProps> = ({ score, size = 'md' }) => {
    const dim = size === 'lg' ? 100 : size === 'md' ? 64 : 40
    const r = size === 'lg' ? 44 : size === 'md' ? 28 : 16
    const stroke = size === 'lg' ? 6 : size === 'md' ? 4 : 3

    const circ = 2 * Math.PI * r
    const offset = circ - (Math.min(10, Math.max(0, score)) / 10) * circ

    const color = score >= 7 ? '#12B76A' : score >= 4 ? '#F59E0B' : '#EF4444'

    return (
        <div className="relative flex items-center justify-center" style={{ width: dim, height: dim }}>
            <svg className="transform -rotate-90" width={dim} height={dim}>
                <circle
                    cx={dim / 2} cy={dim / 2} r={r}
                    stroke="rgba(16,24,40,0.06)" strokeWidth={stroke} fill="none"
                />
                <circle
                    cx={dim / 2} cy={dim / 2} r={r}
                    stroke={color} strokeWidth={stroke} fill="none"
                    strokeDasharray={circ} strokeDashoffset={offset}
                    strokeLinecap="round"
                    className="transition-all duration-1000"
                />
            </svg>
            <div className="absolute flex flex-col items-center">
                <span className={`font-bold leading-none ${size === 'lg' ? 'text-2xl' : size === 'md' ? 'text-lg' : 'text-xs'}`}>
                    {score}
                </span>
                {size !== 'sm' && <span className="text-[8px] text-ink-faint uppercase mt-0.5">/ 10</span>}
            </div>
        </div>
    )
}
