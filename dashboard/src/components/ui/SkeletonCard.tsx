import React from 'react'

interface SkeletonCardProps {
    lines?: number
    height?: string
}

export const SkeletonCard: React.FC<SkeletonCardProps> = ({ lines = 3, height = '120px' }) => {
    return (
        <div
            className="w-full bg-white border border-border rounded-2xl p-6 animate-pulse"
            style={{ height }}
        >
            <div className="flex items-start justify-between mb-4">
                <div className="flex gap-4 items-center">
                    <div className="w-10 h-10 bg-brand-muted rounded-xl"></div>
                    <div className="space-y-2">
                        <div className="h-4 w-32 bg-gray-100 rounded"></div>
                        <div className="h-2 w-20 bg-gray-100 rounded"></div>
                    </div>
                </div>
                <div className="h-4 w-12 bg-gray-100 rounded"></div>
            </div>
            <div className="space-y-3">
                {Array.from({ length: lines }).map((_, i) => (
                    <div
                        key={i}
                        className="h-2 bg-gray-100 rounded"
                        style={{ width: `${100 - (i * 15)}%` }}
                    ></div>
                ))}
            </div>
        </div>
    )
}
