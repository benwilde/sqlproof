CREATE FUNCTION checkout_total(p_subtotal numeric, p_credit numeric)
RETURNS numeric LANGUAGE sql IMMUTABLE AS $$
    SELECT ROUND(GREATEST(p_subtotal - p_credit, 0) +
        CASE WHEN p_subtotal >= 100 THEN 0 ELSE 5 END, 2)
$$;
