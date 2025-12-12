/**
 * Animated Number Counter
 * Counts up to a target number with animation
 */
import React, { useState, useEffect, useRef } from 'react';

const AnimatedCounter = ({
    target,
    duration = 2000,
    prefix = '',
    suffix = '',
    className = ''
}) => {
    const [count, setCount] = useState(0);
    const countRef = useRef(null);
    const startTime = useRef(null);

    useEffect(() => {
        const animate = (timestamp) => {
            if (!startTime.current) startTime.current = timestamp;
            const progress = Math.min((timestamp - startTime.current) / duration, 1);

            // Easing function (ease-out cubic)
            const easeOut = 1 - Math.pow(1 - progress, 3);

            setCount(Math.floor(easeOut * target));

            if (progress < 1) {
                countRef.current = requestAnimationFrame(animate);
            }
        };

        countRef.current = requestAnimationFrame(animate);

        return () => {
            if (countRef.current) {
                cancelAnimationFrame(countRef.current);
            }
        };
    }, [target, duration]);

    return (
        <span className={className}>
            {prefix}{count.toLocaleString()}{suffix}
        </span>
    );
};

export default AnimatedCounter;
