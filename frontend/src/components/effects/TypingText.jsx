/**
 * Typing Effect Component
 * Displays text with typewriter animation
 */
import React, { useState, useEffect } from 'react';

const TypingText = ({
    text,
    speed = 50,
    delay = 0,
    className = '',
    showCursor = true
}) => {
    const [displayedText, setDisplayedText] = useState('');
    const [isTyping, setIsTyping] = useState(false);

    useEffect(() => {
        let timeout;
        let currentIndex = 0;

        const startTyping = () => {
            setIsTyping(true);

            const typeChar = () => {
                if (currentIndex < text.length) {
                    setDisplayedText(text.substring(0, currentIndex + 1));
                    currentIndex++;
                    timeout = setTimeout(typeChar, speed);
                } else {
                    setIsTyping(false);
                }
            };

            typeChar();
        };

        timeout = setTimeout(startTyping, delay);

        return () => clearTimeout(timeout);
    }, [text, speed, delay]);

    return (
        <span className={className}>
            {displayedText}
            {showCursor && (
                <span
                    className="inline-block w-2 h-5 ml-1 bg-cyan-400"
                    style={{
                        animation: isTyping ? 'none' : 'blinkCursor 1s step-end infinite'
                    }}
                />
            )}
        </span>
    );
};

export default TypingText;
