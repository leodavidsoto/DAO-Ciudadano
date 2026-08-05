export const colors = {
    background: '#F7F9FC',
    surface: '#FFFFFF',
    borderLight: '#E5EBF5',
    borderDark: '#DCE5F3',
    ink: '#0B2545',
    text: '#33456B',
    textSoft: '#5C7099',
    primary: '#003897',
    primaryHover: '#002B75',
    primarySoft: '#EAF0FB',
    danger: '#CB2C27',
    dangerSoft: '#FBEAE8',
    success: '#2E8B57',
    successSoft: '#E9F1EC',
    warning: '#B7791F',
    warningSoft: '#FDF6E7',
};

export const typography = {
    title: {
        fontFamily: 'System', // Cambiar a Poppins cuando se instale
        color: colors.ink,
        fontSize: 24,
        fontWeight: 'bold' as const,
    },
    body: {
        fontFamily: 'System', // Cambiar a Open Sans cuando se instale
        color: colors.text,
        fontSize: 16,
    },
    caption: {
        fontFamily: 'System',
        color: colors.textSoft,
        fontSize: 14,
    }
};

export const shadows = {
    light: {
        shadowColor: '#003897',
        shadowOffset: { width: 0, height: 4 },
        shadowOpacity: 0.04,
        shadowRadius: 12,
        elevation: 2,
    },
    strong: {
        shadowColor: '#0B2545',
        shadowOffset: { width: 0, height: 16 },
        shadowOpacity: 0.10,
        shadowRadius: 34,
        elevation: 8,
    }
};

export const radius = {
    sm: 8,
    md: 12,
    lg: 16,
    full: 9999,
};

export const theme = {
    colors,
    typography,
    shadows,
    radius,
};
