/*
 * Copyright (c) Contributors to the Open 3D Engine Project.
 * For complete copyright and license terms please see the LICENSE at the root of this distribution.
 *
 * SPDX-License-Identifier: Apache-2.0 OR MIT
 *
 */

#pragma once

#include <AzCore/Component/Component.h>
#include <AzCore/Component/TickBus.h>
#include <GradientSignal/Ebuses/GradientRequestBus.h>
#include <GradientSignal/GradientSampler.h>
#include <LmbrCentral/Dependency/DependencyMonitor.h>

namespace LmbrCentral
{
    template<typename, typename> class EditorWrappedComponentBase;
}
namespace GradientSignal
{
    template<typename, typename> class EditorGradientComponentBase;
}

namespace NWCapital
{
    //! One New World capital "cookie": a terrain stamp that flattens ground
    //! inside innerRadius to the capital's z and smoothstep-blends back to the
    //! natural height across the inner->outer ring. Matches the client's
    //! load-time heightmap deformation (see tools/physics/terrain_ground.py).
    class CapitalCookie
    {
    public:
        AZ_CLASS_ALLOCATOR(CapitalCookie, AZ::SystemAllocator);
        AZ_RTTI(CapitalCookie, "{4A5F2C1E-9B3D-4E7A-8C2F-1D6B5A9E3F01}");
        virtual ~CapitalCookie() = default;
        static void Reflect(AZ::ReflectContext* context);

        AZ::Vector3 m_position = AZ::Vector3::CreateZero(); //!< capital world position; z is the flat height
        float m_innerRadius = 0.0f;    //!< fully flattened radius (metres)
        float m_outerRadius = 0.0f;    //!< outer edge of the blend ring (metres)
        float m_maxHeightBlend = 1.0f; //!< 0..1 blend strength cap
        float m_edgeNoise = 0.0f;      //!< ring-edge noise amplitude factor (0 = perfect circle)
        float m_edgeNoiseFeatureSize = 0.0f; //!< reserved; client builds a runtime noise table
        float m_groundNoiseScale = 0.0f;     //!< reserved; meaning not yet verified (arena uses 0)
    };

    class CapitalCookieGradientConfig
        : public AZ::ComponentConfig
    {
    public:
        AZ_CLASS_ALLOCATOR(CapitalCookieGradientConfig, AZ::SystemAllocator);
        AZ_RTTI(CapitalCookieGradientConfig, "{7B2E8D4A-1C5F-4A6B-9D3E-2F8A6C1B4E02}");
        static void Reflect(AZ::ReflectContext* context);

        GradientSignal::GradientSampler m_gradientSampler;
        AZStd::vector<CapitalCookie> m_cookies;
        //! Gradient 0..1 -> world metres. Must match the terrain spawner's
        //! height range so the stamp can compare against real heights.
        float m_heightMin = 0.0f;
        float m_heightMax = 2048.0f;
    };

    static constexpr AZ::Uuid CapitalCookieGradientComponentTypeId = AZ::Uuid("{3C9A1F5E-2D7B-4E8A-B6C3-9E1D4A7F2B03}");

    class CapitalCookieGradientComponent
        : public AZ::Component
        , private GradientSignal::GradientRequestBus::Handler
    {
    public:
        template<typename, typename> friend class GradientSignal::EditorGradientComponentBase;
        template<typename, typename> friend class LmbrCentral::EditorWrappedComponentBase;
        AZ_COMPONENT(CapitalCookieGradientComponent, CapitalCookieGradientComponentTypeId);
        static void GetProvidedServices(AZ::ComponentDescriptor::DependencyArrayType& services);
        static void GetIncompatibleServices(AZ::ComponentDescriptor::DependencyArrayType& services);
        static void GetRequiredServices(AZ::ComponentDescriptor::DependencyArrayType& services);
        static void Reflect(AZ::ReflectContext* context);

        CapitalCookieGradientComponent(const CapitalCookieGradientConfig& configuration);
        CapitalCookieGradientComponent() = default;
        ~CapitalCookieGradientComponent() = default;

        //////////////////////////////////////////////////////////////////////////
        // AZ::Component interface implementation
        void Activate() override;
        void Deactivate() override;
        bool ReadInConfig(const AZ::ComponentConfig* baseConfig) override;
        bool WriteOutConfig(AZ::ComponentConfig* outBaseConfig) const override;

    protected:
        //////////////////////////////////////////////////////////////////////////
        // GradientRequestBus
        float GetValue(const GradientSignal::GradientSampleParams& sampleParams) const override;
        void GetValues(AZStd::span<const AZ::Vector3> positions, AZStd::span<float> outValues) const override;
        bool IsEntityInHierarchy(const AZ::EntityId& entityId) const override;

    private:
        float StampHeight(float height, float x, float y) const;

        CapitalCookieGradientConfig m_configuration;
        LmbrCentral::DependencyMonitor m_dependencyMonitor;
    };
}
